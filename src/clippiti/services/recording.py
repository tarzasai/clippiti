"""Recording service: start/stop ffmpeg recording from live HLS playlist."""

from dataclasses import dataclass, field
import ctypes
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from signal import SIGTERM
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from ..services.buffer_engine import SessionRuntime

log = logging.getLogger("clippiti")


@dataclass
class RecordingConfig:
  output_dir: Path
  filename_format: str = "{author}_{timestamp}"
  ffmpeg_path: str = "ffmpeg"
  auto_remux_to_mp4: bool = False


@dataclass
class RecordingSession:
  ts_path: Path
  proc: subprocess.Popen
  started_at: float = field(default_factory=time.monotonic)


class RecordingService:
  def __init__(self) -> None:
    self._session: RecordingSession | None = None

  def is_recording(self) -> bool:
    if self._session is None:
      return False
    if self._session.proc.poll() is not None:
      log.debug("recording: process exited unexpectedly code=%s", self._session.proc.returncode)
      self._session = None
      return False
    return True

  def start(self, runtime: SessionRuntime, cfg: RecordingConfig) -> Path:
    """Start recording from the live playlist. Returns the output .ts path."""
    if self.is_recording():
      raise RuntimeError("recording already in progress")

    if not runtime.playlist_path.exists():
      raise RuntimeError("live playlist does not exist yet; pipeline may not be ready")

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    name = cfg.filename_format.format(
      author=runtime.stream_author,
      category=runtime.stream_category,
      title=runtime.stream_title,
      timestamp=timestamp,
      name=runtime.stream_author,
    )
    safe_name = _safe_filename(name)
    ts_path = cfg.output_dir / f"{safe_name}.ts"

    cmd = [
      cfg.ffmpeg_path,
      "-hide_banner",
      "-loglevel", "error",
      "-y",
      "-i", str(runtime.playlist_path),
      "-map", "0:v:0?",
      "-map", "0:a?",
      "-sn",
      "-dn",
      "-c:v", "copy",
      "-c:a", "copy",
      str(ts_path),
    ]
    log.debug("recording: starting ffmpeg command: %s", cmd)

    proc = _spawn_ffmpeg(
      cmd,
      stderr_path=_stderr_log_path(ts_path),
    )

    self._session = RecordingSession(ts_path=ts_path, proc=proc)
    log.debug("recording: started pid=%s output=%s", proc.pid, ts_path)
    return ts_path

  def stop(self) -> Path:
    """Stop recording and return the captured transport stream path."""
    if self._session is None:
      raise RuntimeError("not recording")

    session = self._session
    self._session = None

    _graceful_stop(session.proc)
    log.debug("recording: stopped ts=%s", session.ts_path)

    return session.ts_path

  def finalize(self, ts_path: Path, cfg: RecordingConfig) -> tuple[Path, bool]:
    """Finalize a stopped recording. Returns (final_path, remuxed)."""

    if not cfg.auto_remux_to_mp4:
      return ts_path, False

    mp4_path = ts_path.with_suffix(".mp4")
    remuxed = _remux(ts_path, mp4_path, cfg.ffmpeg_path, _stderr_log_path(ts_path))
    if remuxed:
      ts_path.unlink(missing_ok=True)
      return mp4_path, True
    return ts_path, False

  def abort(self) -> None:
    """Stop recording without returning a result (used on shutdown)."""
    if self._session is None:
      return
    session = self._session
    self._session = None
    _graceful_stop(session.proc)
    log.debug("recording: aborted ts=%s", session.ts_path)

  def elapsed_seconds(self) -> float:
    if self._session is None:
      return 0.0
    return time.monotonic() - self._session.started_at


class _StopWorker(QObject):
  finished = pyqtSignal(object)
  failed = pyqtSignal(object)

  def __init__(self, recording: RecordingService) -> None:
    super().__init__()
    self._recording = recording

  @pyqtSlot()
  def run(self) -> None:
    try:
      ts_path = self._recording.stop()
    except Exception as exc:
      self.failed.emit(exc)
      return
    self.finished.emit(ts_path)


class AsyncRecordingService(QObject):
  stop_finished = pyqtSignal(object)
  stop_failed = pyqtSignal(object)
  stop_requested = pyqtSignal()

  def __init__(self, parent: QObject | None = None) -> None:
    super().__init__(parent)
    self._service = RecordingService()
    self._stop_in_progress = False
    self._stop_thread = QThread(self)
    self._stop_worker = _StopWorker(self._service)
    self._stop_worker.moveToThread(self._stop_thread)

    self.stop_requested.connect(self._stop_worker.run)
    self._stop_worker.finished.connect(self._handle_stop_finished)
    self._stop_worker.failed.connect(self._handle_stop_failed)
    self._stop_thread.finished.connect(self._stop_worker.deleteLater)
    self._stop_thread.start()

  def is_recording(self) -> bool:
    return self._service.is_recording()

  def start(self, runtime: SessionRuntime, cfg: RecordingConfig) -> Path:
    return self._service.start(runtime, cfg)

  def request_stop(self) -> bool:
    if self._stop_in_progress:
      return False
    self._stop_in_progress = True
    self.stop_requested.emit()
    return True

  def abort(self) -> None:
    self._service.abort()

  def elapsed_seconds(self) -> float:
    return self._service.elapsed_seconds()

  def shutdown(self) -> None:
    self._stop_thread.quit()
    self._stop_thread.wait(3000)

  @pyqtSlot(object)
  def _handle_stop_finished(self, ts_path_obj: object) -> None:
    self._stop_in_progress = False
    self.stop_finished.emit(ts_path_obj)

  @pyqtSlot(object)
  def _handle_stop_failed(self, exc_obj: object) -> None:
    self._stop_in_progress = False
    self.stop_failed.emit(exc_obj)


def _safe_filename(name: str) -> str:
  keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ")
  return "".join(c if c in keep else "_" for c in name).strip("_").replace(" ", "_")


def _preexec() -> None:
  try:
    libc = ctypes.CDLL(None)
    libc.prctl(1, SIGTERM, 0, 0, 0)
  except Exception:
    pass


def _graceful_stop(proc: subprocess.Popen) -> None:
  if proc.poll() is not None:
    return
  try:
    proc.terminate()
    proc.wait(timeout=5.0)
  except Exception:
    pass
  if proc.poll() is None:
    try:
      proc.kill()
      proc.wait(timeout=2.0)
    except Exception:
      pass


def _stderr_log_path(output_path: Path) -> Path | None:
  if not log.isEnabledFor(logging.DEBUG):
    return None
  return output_path.with_suffix(".stderr.log")


def _spawn_ffmpeg(cmd: list[str], stderr_path: Path | None) -> subprocess.Popen:
  stderr_target = subprocess.DEVNULL
  stderr_fp = None
  if stderr_path is not None:
    stderr_fp = stderr_path.open("wb")
    stderr_target = stderr_fp

  try:
    return subprocess.Popen(
      cmd,
      stdout=subprocess.DEVNULL,
      stderr=stderr_target,
      text=False,
      preexec_fn=_preexec if os.name == "posix" else None,
    )
  finally:
    if stderr_fp is not None:
      stderr_fp.close()


def _remux(src: Path, dst: Path, ffmpeg_path: str, stderr_path: Path | None) -> bool:
  cmd = [
    ffmpeg_path,
    "-hide_banner", "-loglevel", "error",
    "-y",
    "-i", str(src),
    "-map", "0:v:0?",
    "-map", "0:a?",
    "-sn",
    "-dn",
    "-c", "copy",
    "-movflags", "+faststart",
    str(dst),
  ]
  log.debug("recording: remuxing %s -> %s", src, dst)
  stderr_target = subprocess.DEVNULL
  stderr_fp = None
  if stderr_path is not None:
    stderr_fp = stderr_path.open("wb")
    stderr_target = stderr_fp
  try:
    proc = subprocess.run(
      cmd,
      check=False,
      stdout=subprocess.DEVNULL,
      stderr=stderr_target,
      timeout=120,
    )
    if proc.returncode == 0:
      log.debug("recording: remux successful")
      return True
    if stderr_path is not None:
      log.warning("recording: remux failed code=%s stderr_log=%s", proc.returncode, stderr_path)
    else:
      log.warning("recording: remux failed code=%s", proc.returncode)
    return False
  except Exception as exc:
    log.warning("recording: remux exception: %s", exc)
    return False
  finally:
    if stderr_fp is not None:
      stderr_fp.close()
