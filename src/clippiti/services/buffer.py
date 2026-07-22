"""Buffer engine: single-session rolling HLS pipeline (Streamlink API -> ffmpeg)."""

from dataclasses import dataclass
import logging
from pathlib import Path
from signal import SIGTERM
import os
import shutil
import subprocess
import threading
import time
import ctypes

from .slsession import StreamMetadata, StreamPump, open_stream
from streamlink.stream.stream import Stream


log = logging.getLogger("clippiti")


@dataclass
class SessionRuntime:
  url: str
  desired_quality: str
  stream_title: str
  stream_author: str
  stream_category: str
  plugin: str
  segment_dir: Path
  playlist_path: Path
  segment_seconds: int
  window_segments: int
  status: str = "loading"
  stream_pump: StreamPump | None = None
  ffmpeg_proc: subprocess.Popen | None = None
  ffmpeg_stderr_path: Path | None = None

  @property
  def buffer_seconds(self) -> int:
    return self.segment_seconds * self.window_segments


def _linux_parent_death_preexec() -> None:
  # Ensure child dies if this Python process crashes (Linux only).
  if os.name != "posix":
    return
  try:
    libc = ctypes.CDLL(None)
    PR_SET_PDEATHSIG = 1
    libc.prctl(PR_SET_PDEATHSIG, SIGTERM, 0, 0, 0)
    log.debug("configured PR_SET_PDEATHSIG for child process")
  except Exception:
    # Best effort only.
    log.debug("buffer_engine: failed to configure PR_SET_PDEATHSIG", exc_info=True)
    return


def _child_process_kwargs() -> dict[str, object]:
  kwargs: dict[str, object] = {"text": False}
  if os.name != "posix":
    return kwargs

  # preexec_fn is unsafe in multithreaded Python programs. Startup now runs
  # in a Qt worker thread, so only use it from main thread.
  if threading.current_thread() is threading.main_thread():
    kwargs["preexec_fn"] = _linux_parent_death_preexec
  else:
    log.debug("buffer_engine: skipping preexec_fn in non-main thread for subprocess safety")
  return kwargs


def _stderr_log_path(segment_dir: Path, name: str) -> Path | None:
  if not log.isEnabledFor(logging.DEBUG):
    return None
  return segment_dir / name


def _stderr_target(stderr_path: Path | None):
  if stderr_path is None:
    return subprocess.DEVNULL, None
  stderr_fp = stderr_path.open("wb")
  return stderr_fp, stderr_fp


def start_single_session_pipeline(
  *,
  workdir: Path,
  ffmpeg_path: str,
  url: str,
  quality: str,
  stream: Stream,
  segment_seconds: int,
  window_segments: int,
  metadata: StreamMetadata,
  startup_timeout_s: int = 25,
  cancel_event: threading.Event | None = None,
) -> SessionRuntime:
  segment_seconds = max(1, int(segment_seconds))
  window_segments = max(2, int(window_segments))

  session_id = time.strftime("%Y%m%d_%H%M%S")
  segment_dir = workdir / "sessions" / session_id
  segment_dir.mkdir(parents=True, exist_ok=True)
  (segment_dir / "owner.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
  playlist_path = segment_dir / "live.m3u8"
  ffmpeg_stderr_path = _stderr_log_path(segment_dir, "ffmpeg.stderr.log")

  ffmpeg_stderr_target, ffmpeg_stderr_fp = _stderr_target(ffmpeg_stderr_path)

  ffmpeg_cmd = [
    ffmpeg_path,
    "-hide_banner",
    "-loglevel",
    "error",
    "-y",
    "-i",
    "pipe:0",
    "-c",
    "copy",
    "-f",
    "hls",
    "-hls_time",
    str(segment_seconds),
    "-hls_list_size",
    str(window_segments),
    "-hls_flags",
    "delete_segments+append_list+temp_file",
    "-hls_segment_filename",
    str(segment_dir / "seg_%05d.ts"),
    str(playlist_path),
  ]

  log.debug("buffer_engine: starting pipeline session_id=%s segment_dir=%s", session_id, segment_dir)
  log.debug("buffer_engine: ffmpeg command built: %s", ffmpeg_cmd)

  if cancel_event is not None and cancel_event.is_set():
    log.debug("buffer_engine: pipeline startup cancelled before process launch")
    shutil.rmtree(segment_dir, ignore_errors=True)
    raise RuntimeError("buffer pipeline startup cancelled")

  # Open the Streamlink stream first so an offline/broken stream fails fast
  # before we spawn ffmpeg.
  stream_fd, prebuffer = open_stream(stream)
  log.debug("buffer_engine: stream opened, prebuffer=%d bytes", len(prebuffer))

  ffmpeg_proc = None
  stream_pump = None

  try:
    child_kwargs = _child_process_kwargs()
    ffmpeg_proc = subprocess.Popen(
      ffmpeg_cmd,
      stdin=subprocess.PIPE,
      stdout=subprocess.DEVNULL,
      stderr=ffmpeg_stderr_target,
      **child_kwargs,
    )
    if ffmpeg_proc.stdin is None:
      raise RuntimeError("failed to open ffmpeg stdin")
    log.debug("buffer_engine: ffmpeg process started pid=%s", ffmpeg_proc.pid)

    stream_pump = StreamPump(stream_fd, ffmpeg_proc.stdin, prebuffer=prebuffer)
    stream_pump.start()
    log.debug("buffer_engine: stream pump started")
  except Exception:
    try:
      stream_fd.close()
    except Exception:
      pass
    if ffmpeg_proc is not None:
      try:
        ffmpeg_proc.kill()
      except Exception:
        pass
    raise
  finally:
    if ffmpeg_stderr_fp is not None:
      ffmpeg_stderr_fp.close()

  runtime = SessionRuntime(
    url=url,
    desired_quality=quality,
    stream_title=metadata.title,
    stream_author=metadata.author,
    stream_category=metadata.category,
    plugin=metadata.plugin,
    segment_dir=segment_dir,
    playlist_path=playlist_path,
    segment_seconds=segment_seconds,
    window_segments=window_segments,
    status="loading",
    stream_pump=stream_pump,
    ffmpeg_proc=ffmpeg_proc,
    ffmpeg_stderr_path=ffmpeg_stderr_path,
  )

  deadline = time.monotonic() + max(1, startup_timeout_s)
  log.debug("buffer_engine: waiting for playlist readiness timeout=%ss path=%s", max(1, startup_timeout_s), playlist_path)
  while time.monotonic() < deadline:
    if cancel_event is not None and cancel_event.is_set():
      log.debug("buffer_engine: pipeline startup cancelled while waiting for playlist readiness")
      terminate_runtime(runtime)
      cleanup_runtime_artifacts(runtime)
      raise RuntimeError("buffer pipeline startup cancelled")
    if playlist_path.exists() and playlist_path.stat().st_size > 0:
      runtime.status = "live"
      log.debug("buffer_engine: playlist became available size=%s", playlist_path.stat().st_size)
      return runtime
    if stream_pump.poll() is not None:
      log.debug("buffer_engine: stream pump ended early code=%s error=%s", stream_pump.poll(), stream_pump.error)
      raise RuntimeError("stream ended before playlist became available")
    if ffmpeg_proc.poll() is not None:
      log.debug("buffer_engine: ffmpeg exited early code=%s", ffmpeg_proc.returncode)
      raise RuntimeError("ffmpeg exited before playlist became available")
    time.sleep(0.15)

  log.debug("buffer_engine: playlist startup timed out path=%s", playlist_path)
  raise RuntimeError("buffer pipeline startup timed out before live.m3u8 became available")


def terminate_runtime(runtime: SessionRuntime) -> None:
  log.debug("buffer_engine: terminating runtime for segment_dir=%s", runtime.segment_dir)

  # Stop the stream pump first so it stops feeding ffmpeg and closes its stdin.
  if runtime.stream_pump is not None:
    try:
      log.debug("buffer_engine: stopping stream pump")
      runtime.stream_pump.stop()
    except Exception:
      log.debug("buffer_engine: stream pump stop failed", exc_info=True)

  proc = runtime.ffmpeg_proc
  if proc is None or proc.poll() is not None:
    return

  try:
    log.debug("buffer_engine: sending terminate to pid=%s", proc.pid)
    proc.terminate()
  except Exception:
    log.debug("buffer_engine: terminate failed for pid=%s", proc.pid, exc_info=True)

  try:
    proc.wait(timeout=3.0)
    log.debug("buffer_engine: process exited after terminate pid=%s code=%s", proc.pid, proc.returncode)
    return
  except Exception:
    log.debug("buffer_engine: process did not exit after terminate pid=%s", proc.pid, exc_info=True)
  try:
    log.debug("buffer_engine: sending kill to pid=%s", proc.pid)
    proc.kill()
  except Exception:
    log.debug("buffer_engine: kill failed for pid=%s", proc.pid, exc_info=True)
  try:
    proc.wait(timeout=1.0)
  except Exception:
    log.debug("buffer_engine: process still did not exit after kill pid=%s", proc.pid, exc_info=True)
  else:
    log.debug("buffer_engine: process exited after kill pid=%s code=%s", proc.pid, proc.returncode)


def cleanup_runtime_artifacts(runtime: SessionRuntime) -> None:
  # A short retry loop helps when ffmpeg exits slightly after SIGTERM.
  for attempt in range(6):
    shutil.rmtree(runtime.segment_dir, ignore_errors=True)
    if not runtime.segment_dir.exists():
      log.debug("buffer_engine: runtime artifacts removed attempt=%s dir=%s", attempt + 1, runtime.segment_dir)
      break
    log.debug("buffer_engine: runtime artifacts still present attempt=%s dir=%s", attempt + 1, runtime.segment_dir)
    time.sleep(0.1)


def _pid_is_alive(pid: int) -> bool:
  if pid <= 0:
    return False
  try:
    os.kill(pid, 0)
    return True
  except OSError:
    return False


def cleanup_orphan_session_dirs(workdir: Path, current_pid: int | None = None) -> int:
  sessions_root = workdir / "sessions"
  if not sessions_root.exists():
    log.debug("no sessions root to scan: %s", sessions_root)
    return 0

  active_pid = current_pid if current_pid is not None else os.getpid()
  removed = 0
  log.debug("buffer_engine: scanning orphan session dirs in %s active_pid=%s", sessions_root, active_pid)

  for entry in sessions_root.iterdir():
    if not entry.is_dir():
      continue

    owner_file = entry / "owner.pid"
    owner_pid = 0
    if owner_file.exists():
      try:
        owner_pid = int(owner_file.read_text(encoding="utf-8").strip())
      except (TypeError, ValueError):
        owner_pid = 0

    if owner_pid == active_pid:
      log.debug("buffer_engine: keeping session dir owned by current process: %s", entry)
      continue

    if owner_pid > 0 and _pid_is_alive(owner_pid):
      log.debug("buffer_engine: keeping session dir with live owner pid=%s dir=%s", owner_pid, entry)
      continue

    shutil.rmtree(entry, ignore_errors=True)
    removed += 1
    log.debug("buffer_engine: removed orphan session dir owner_pid=%s dir=%s", owner_pid, entry)

  log.debug("buffer_engine: orphan session cleanup removed=%s", removed)
  return removed
