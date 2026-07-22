"""Snapshot service: save the current on-screen frame via mpv.

mpv writes its current frame to a temporary file; the viewer's rotation is then
applied to that file (mpv's software screenshot ignores ``video-rotate``), and
the finished image is moved to the snapshot output directory.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from collections.abc import Callable
import logging
import shutil
import tempfile

from PyQt6.QtCore import QObject, pyqtSignal
from PIL import Image

from .buffer import SessionRuntime

log = logging.getLogger("clippiti")


def _safe_filename(name: str) -> str:
  keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ")
  return "".join(ch if ch in keep else "_" for ch in name).strip("_").replace(" ", "_")


def _orient(path: Path, degrees: int) -> None:
  """Rotate the saved frame to match the viewer's clockwise video-rotate.

  mpv's software screenshot (screenshot-sw) bypasses the VO, so it writes the
  frame in its original orientation regardless of ``video-rotate``. Pillow
  rotates counter-clockwise for positive angles, so the clockwise angle is
  negated; ``expand=True`` keeps the whole rotated frame.
  """
  if not degrees:
    return
  with Image.open(path) as image:
    image.rotate(-degrees, expand=True).save(path)


class Screenshotter(Protocol):
  """The video surface: asynchronously writes the current frame to a file.

  ``on_done(success)`` is invoked when the (async) capture completes; the call
  must be async because a synchronous mpv screenshot deadlocks the render API.
  """

  def save_screenshot(self, path: Path, on_done: Callable[[bool], None]) -> bool: ...


@dataclass
class SnapshotConfig:
  output_dir: Path
  filename_format: str = "{author}.{timestamp}"


class SnapshotService(QObject):
  """Saves the on-screen frame via mpv, then moves it into the output dir."""

  snapshot_ready = pyqtSignal(str)   # output path
  snapshot_failed = pyqtSignal(str)  # error message

  def __init__(self, config: SnapshotConfig, player: Screenshotter, parent: QObject | None = None) -> None:
    super().__init__(parent)
    self._config = config
    self._player = player

  def set_config(self, config: SnapshotConfig) -> None:
    self._config = config

  def capture(self, runtime: SessionRuntime, rotation: int = 0) -> bool:
    """Start an async mpv screenshot of the current frame.

    ``rotation`` is the viewer's clockwise ``video-rotate`` (applied to the saved
    image afterwards). Returns True if the capture was started; the
    ``snapshot_ready`` / ``snapshot_failed`` signals fire later when it completes.
    """
    output_path = self._build_output_path(
      runtime.stream_author,
      runtime.stream_category,
      runtime.stream_title,
    )

    # mpv writes to a local temp file (not the destination) so the frame can be
    # rotated to match the viewer before being published, and so an external
    # process moving files out of the output dir cannot race it.
    try:
      stage_dir = Path(tempfile.mkdtemp(prefix="clippiti_snap_"))
    except Exception:
      log.exception("snapshot: failed to create temp dir")
      return False

    temp_output = stage_dir / "frame.png"

    def _finalize(ok: bool) -> None:
      # Invoked on mpv's event thread; Qt signals queue to the GUI thread.
      if not ok:
        log.warning("snapshot: mpv screenshot failed")
        shutil.rmtree(stage_dir, ignore_errors=True)
        self.snapshot_failed.emit("screenshot failed")
        return

      moved = False
      try:
        _orient(temp_output, rotation)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_output), str(output_path))
        moved = True
      except Exception as exc:
        log.exception("snapshot: failed to finalize image %s", output_path)
        self.snapshot_failed.emit(str(exc))
      finally:
        shutil.rmtree(stage_dir, ignore_errors=True)

      if moved:
        log.info("snapshot: saved output=%s", output_path)
        self.snapshot_ready.emit(str(output_path))

    if not self._player.save_screenshot(temp_output, _finalize):
      log.warning("snapshot: could not start screenshot")
      shutil.rmtree(stage_dir, ignore_errors=True)
      return False
    return True

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
