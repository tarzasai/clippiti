"""Deliverable 2 buffer engine: metadata probe + single-session rolling HLS pipeline."""

from dataclasses import dataclass
from pathlib import Path
from signal import SIGTERM
import json
import os
import shutil
import subprocess
import time
import ctypes

from .streamlink_args import merge_streamlink_args


@dataclass
class StreamMetadata:
    plugin: str
    author: str
    category: str
    title: str


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
    streamlink_proc: subprocess.Popen | None = None
    ffmpeg_proc: subprocess.Popen | None = None
    streamlink_stderr_path: Path | None = None
    ffmpeg_stderr_path: Path | None = None

    @property
    def buffer_seconds(self) -> int:
        return self.segment_seconds * self.window_segments


def _metadata_command(url: str, default_args: str, cli_args: str) -> list[str]:
    merged = merge_streamlink_args(default_args, cli_args)
    return ["streamlink", *merged, "--json", url]


def _pipeline_streamlink_command(url: str, quality: str, default_args: str, cli_args: str) -> list[str]:
    merged = merge_streamlink_args(default_args, cli_args)
    return ["streamlink", *merged, "--stdout", url, quality]


def _linux_parent_death_preexec() -> None:
    # Ensure child dies if this Python process crashes (Linux only).
    if os.name != "posix":
        return
    try:
        libc = ctypes.CDLL(None)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, SIGTERM, 0, 0, 0)
    except Exception:
        # Best effort only.
        return


def resolve_stream_metadata(url: str, default_args: str, cli_args: str, timeout_s: int = 25) -> StreamMetadata:
    cmd = _metadata_command(url, default_args, cli_args)
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=max(1, timeout_s),
    )

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "streamlink metadata probe failed").strip()
        raise RuntimeError(err)

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("streamlink --json returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("streamlink --json response format is invalid")

    plugin = str(payload.get("plugin", "unknown") or "unknown")
    meta = payload.get("metadata", {})
    if not isinstance(meta, dict):
        meta = {}

    author = str(meta.get("author", "unknown") or "unknown")
    category = str(meta.get("category", "unknown") or "unknown")
    title = str(meta.get("title", url) or url)

    return StreamMetadata(plugin=plugin, author=author, category=category, title=title)


def start_single_session_pipeline(
    *,
    workdir: Path,
    ffmpeg_path: str,
    url: str,
    quality: str,
    default_args: str,
    cli_args: str,
    segment_seconds: int,
    window_segments: int,
    metadata: StreamMetadata,
    startup_timeout_s: int = 25,
) -> SessionRuntime:
    segment_seconds = max(1, int(segment_seconds))
    window_segments = max(2, int(window_segments))

    session_id = time.strftime("%Y%m%d_%H%M%S")
    segment_dir = workdir / "sessions" / session_id
    segment_dir.mkdir(parents=True, exist_ok=True)
    (segment_dir / "owner.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    playlist_path = segment_dir / "live.m3u8"
    streamlink_stderr_path = segment_dir / "streamlink.stderr.log"
    ffmpeg_stderr_path = segment_dir / "ffmpeg.stderr.log"

    streamlink_stderr_fp = streamlink_stderr_path.open("wb")
    ffmpeg_stderr_fp = ffmpeg_stderr_path.open("wb")

    streamlink_cmd = _pipeline_streamlink_command(url, quality, default_args, cli_args)
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

    try:
        streamlink_proc = subprocess.Popen(
            streamlink_cmd,
            stdout=subprocess.PIPE,
            stderr=streamlink_stderr_fp,
            text=False,
            preexec_fn=_linux_parent_death_preexec if os.name == "posix" else None,
        )
        if streamlink_proc.stdout is None:
            raise RuntimeError("failed to capture streamlink stdout")

        ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=streamlink_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=ffmpeg_stderr_fp,
            text=False,
            preexec_fn=_linux_parent_death_preexec if os.name == "posix" else None,
        )
        streamlink_proc.stdout.close()
    finally:
        streamlink_stderr_fp.close()
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
        streamlink_proc=streamlink_proc,
        ffmpeg_proc=ffmpeg_proc,
        streamlink_stderr_path=streamlink_stderr_path,
        ffmpeg_stderr_path=ffmpeg_stderr_path,
    )

    deadline = time.monotonic() + max(1, startup_timeout_s)
    while time.monotonic() < deadline:
        if playlist_path.exists() and playlist_path.stat().st_size > 0:
            runtime.status = "live"
            return runtime
        if streamlink_proc.poll() is not None:
            message = "streamlink exited before playlist became available"
            raise RuntimeError(message)
        if ffmpeg_proc.poll() is not None:
            raise RuntimeError("ffmpeg exited before playlist became available")
        time.sleep(0.15)

    raise RuntimeError("buffer pipeline startup timed out before live.m3u8 became available")


def terminate_runtime(runtime: SessionRuntime) -> None:
    procs = [runtime.ffmpeg_proc, runtime.streamlink_proc]

    for proc in procs:
        if proc is None or proc.poll() is not None:
            continue
        try:
            proc.terminate()
        except Exception:
            pass

    for proc in procs:
        if proc is None:
            continue
        if proc.poll() is not None:
            continue
        try:
            proc.wait(timeout=3.0)
            continue
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=1.0)
        except Exception:
            pass


def cleanup_runtime_artifacts(runtime: SessionRuntime) -> None:
    # A short retry loop helps when ffmpeg exits slightly after SIGTERM.
    for _ in range(6):
        shutil.rmtree(runtime.segment_dir, ignore_errors=True)
        if not runtime.segment_dir.exists():
            break
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
        return 0

    active_pid = current_pid if current_pid is not None else os.getpid()
    removed = 0

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
            continue

        if owner_pid > 0 and _pid_is_alive(owner_pid):
            continue

        shutil.rmtree(entry, ignore_errors=True)
        removed += 1

    return removed
