"""Snapshot service: extract a single frame from the live HLS buffer.

Snapshots are produced from the buffered ``.ts`` segments rather than from mpv,
so the saved image always has correct colors regardless of mpv's display-only
transforms (which corrupt chroma in mpv's ``video`` screenshot when a rotation
is active). The frame at the requested playback position is extracted with
ffmpeg on a background queue, then any active display rotation is applied with
Pillow.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import shutil
import tempfile

from PyQt6.QtCore import QObject, pyqtSignal
from PIL import Image

from .buffer_engine import SessionRuntime
from .clipper import ClipService
from .remux_queue import FfmpegJob, FfmpegJobQueueService, FfmpegJobResult

log = logging.getLogger("clippiti")

_FFMPEG_QUIET = ["-hide_banner", "-loglevel", "error"]

# The displayed frame lands a few frames behind the button press, so nudge the
# target time slightly earlier to match what the viewer saw at click time.
_CLICK_LEAD_SECONDS = 0.75


def _safe_filename(name: str) -> str:
  keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ")
  return "".join(ch if ch in keep else "_" for ch in name).strip("_").replace(" ", "_")


@dataclass
class SnapshotConfig:
  output_dir: Path
  ffmpeg_path: str = "ffmpeg"
  filename_format: str = "{author}.{timestamp}"


@dataclass
class _SnapshotContext:
  stage_dir: Path
  output_path: Path
  rotation: int


class SnapshotService(QObject):
  """Queue that extracts snapshot frames from the buffer and orients them."""

  snapshot_ready = pyqtSignal(str)   # output path
  snapshot_failed = pyqtSignal(str)  # error message

  def __init__(self, config: SnapshotConfig, queue: FfmpegJobQueueService, parent: QObject | None = None) -> None:
    super().__init__(parent)
    self._config = config
    self._queue = queue
    self._queue.job_finished.connect(self._on_job_finished)

  def set_config(self, config: SnapshotConfig) -> None:
    self._config = config

  def capture(
    self,
    runtime: SessionRuntime,
    lag_seconds: float,
    rotation: int,
  ) -> bool:
    """Queue extraction of the on-screen frame from the buffered segments.

    ``lag_seconds`` is how far behind the live edge the player is currently
    displaying; the target position is measured back from the newest buffered
    frame so the snapshot matches what the viewer sees.
    """
    try:
      segments = ClipService.parse_m3u8(runtime.playlist_path)
    except Exception:
      log.exception("snapshot: failed to read live playlist")
      return False
    if not segments:
      log.warning("snapshot: no buffered segments available")
      return False

    total_seconds = sum(duration for _, duration in segments)
    position = total_seconds - max(0.0, float(lag_seconds)) - _CLICK_LEAD_SECONDS
    position = min(max(0.0, position), total_seconds)

    seg_path, offset = self._locate_frame(segments, position)
    if seg_path is None or not seg_path.exists():
      log.warning("snapshot: target segment unavailable position=%.3f", position)
      return False

    # Copy the segment out of the rolling window immediately so it cannot be
    # deleted while ffmpeg is reading it.
    try:
      stage_dir = Path(tempfile.mkdtemp(prefix="clippiti_snap_"))
      staged = stage_dir / seg_path.name
      shutil.copy2(seg_path, staged)
    except Exception:
      log.exception("snapshot: failed to stage segment")
      return False

    output_path = self._build_output_path(
      runtime.stream_author,
      runtime.stream_category,
      runtime.stream_title,
    )

    # ffmpeg writes to a local temp file (not the destination) so that the
    # success check and rotation are not disrupted by an external process
    # moving/consuming the file from the output directory. The finished,
    # rotated image is moved to the destination only at the end.
    temp_output = stage_dir / "frame.png"
    stderr_path = stage_dir / "ffmpeg.stderr.log"
    job = FfmpegJob(
      target_path=temp_output,
      ffmpeg_path=self._config.ffmpeg_path,
      arguments=[
        *_FFMPEG_QUIET,
        "-y",
        # Input seeking (-ss before -i) seeks to the nearest keyframe and always
        # yields a frame. Output seeking failed near the live edge, where the
        # targeted frame is in a segment not yet fully flushed to disk, causing
        # ffmpeg to exit 0 with no output.
        "-ss",
        f"{offset:.3f}",
        "-i",
        str(staged),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(temp_output),
      ],
      stderr_path=stderr_path,
      kind="snapshot",
      context=_SnapshotContext(
        stage_dir=stage_dir,
        output_path=output_path,
        rotation=rotation,
      ),
    )
    log.debug(
      "snapshot: capture rotation=%s lag=%.3f position=%.3f total=%.3f segment=%s offset=%.3f",
      rotation,
      float(lag_seconds),
      position,
      total_seconds,
      seg_path.name,
      offset,
    )
    self._queue.enqueue(job)
    return True

  def _on_job_finished(self, result_obj: object) -> None:
    if not isinstance(result_obj, FfmpegJobResult):
      return
    job = result_obj.job
    if job.kind != "snapshot":
      return
    ctx = job.context
    if not isinstance(ctx, _SnapshotContext):
      return

    if not result_obj.success:
      error = result_obj.error or "extraction failed"
      stderr_text = ""
      try:
        stderr_file = ctx.stage_dir / "ffmpeg.stderr.log"
        if stderr_file.exists():
          stderr_text = stderr_file.read_text(errors="replace").strip()
      except Exception:
        pass
      log.warning(
        "snapshot: ffmpeg failed: %s output_exists=%s stderr=%s",
        error,
        job.target_path.exists(),
        stderr_text or "(empty)",
      )
      shutil.rmtree(ctx.stage_dir, ignore_errors=True)
      self.snapshot_failed.emit(error)
      return

    try:
      self._orient(job.target_path, ctx.rotation)
      ctx.output_path.parent.mkdir(parents=True, exist_ok=True)
      shutil.move(str(job.target_path), str(ctx.output_path))
    except Exception as exc:
      log.exception("snapshot: failed to finalize image path=%s", ctx.output_path)
      self.snapshot_failed.emit(str(exc))
      return
    finally:
      shutil.rmtree(ctx.stage_dir, ignore_errors=True)

    log.debug("snapshot: saved rotation=%s path=%s", ctx.rotation, ctx.output_path)
    self.snapshot_ready.emit(str(ctx.output_path))

  @staticmethod
  def _locate_frame(
    segments: list[tuple[Path, float]],
    position_seconds: float,
  ) -> tuple[Path | None, float]:
    """Return the segment containing ``position_seconds`` and the in-segment offset."""
    cursor = 0.0
    last: tuple[Path, float, float] | None = None
    for seg_path, duration in segments:
      seg_start = cursor
      last = (seg_path, duration, seg_start)
      if position_seconds < seg_start + duration:
        return seg_path, max(0.0, position_seconds - seg_start)
      cursor = seg_start + duration
    if last is not None:
      seg_path, duration, _ = last
      return seg_path, max(0.0, duration - 0.1)
    return None, 0.0

  @staticmethod
  def _orient(target_path: Path, degrees: int) -> None:
    """Rotate the extracted frame to match the viewer's on-screen rotation.

    ffmpeg writes the decoded frame without the viewer's manual rotation, so it
    is applied here. The snapshot must reflect exactly what the user sees,
    regardless of the stream's native geometry. Pillow rotates counter-clockwise
    for positive angles, so the mpv clockwise angle is negated.
    """
    if not degrees:
      return
    with Image.open(target_path) as image:
      image.rotate(-degrees, expand=True).save(target_path)

  def _build_output_path(
    self,
    author: str,
    category: str,
    title: str,
  ) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
      name = self._config.filename_format.format(
        author=author,
        category=category,
        title=title,
        timestamp=ts,
      )
    except Exception:
      name = f"{author}.{ts}"
    safe_name = _safe_filename(name) or f"snapshot_{ts}"
    output_dir = self._config.output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{safe_name}.png"
