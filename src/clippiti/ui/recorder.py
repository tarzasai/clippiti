"""Recording lifecycle orchestration: start, stop, and post-stop remux.

Mirrors ClipWorkflow: a QObject controller that takes the AppContext and emits
UI-intent signals (OSD messages, recording-state changes) that MainWindow
subscribes to, keeping widget access out of the workflow.
"""

from pathlib import Path
import logging

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from ..app_context import AppContext
from ..services.recording import RecordingConfig
from ..services.remuxer import FfmpegJobResult, RemuxJob

log = logging.getLogger("clippiti")


class RecordingWorkflow(QObject):
  """Owns the recording lifecycle and the post-stop container/remux decision."""

  # MainWindow (which owns the OSD + toolbar) subscribes to these.
  message_requested = pyqtSignal(str, object, bool)  # title, detail, persistent
  recording_state_changed = pyqtSignal(bool)         # True=started, False=stopped

  def __init__(self, ctx: AppContext, parent: QObject | None = None) -> None:
    super().__init__(parent)
    self._ctx = ctx
    self._stop_in_progress = False
    self._stop_cfg: RecordingConfig | None = None
    ctx.recording.stop_finished.connect(self._on_stop_finished)
    ctx.recording.stop_failed.connect(self._on_stop_failed)
    ctx.remux_queue.job_finished.connect(self._on_remux_job_finished)

  def is_recording(self) -> bool:
    return self._ctx.recording.is_recording()

  def toggle(self) -> None:
    if self._ctx.recording.is_recording():
      self.stop()
    else:
      self.start()

  def start(self) -> None:
    if self._ctx.runtime is None:
      self.message_requested.emit("Recording", "Stream not ready yet", False)
      return
    if self._ctx.recording_cfg is None:
      self.message_requested.emit("Recording", "Recording not configured", False)
      return
    try:
      path = self._ctx.recording.start(self._ctx.runtime, self._ctx.recording_cfg)
      # Rotation is captured at start; it is blocked while recording.
      self._ctx.recording_rotation = self._ctx.rotation
      log.info("recording: started output=%s", path)
      self.message_requested.emit("Recording", f"Saving to {path.name}", False)
      self.recording_state_changed.emit(True)
    except Exception as exc:
      log.error("recording: failed to start: %s", exc)
      self.message_requested.emit("Recording failed", str(exc), False)

  def stop(self) -> None:
    if self._stop_in_progress:
      return
    try:
      cfg = self._ctx.recording_cfg or RecordingConfig(output_dir=Path.home())
      self._stop_cfg = cfg
      self._stop_in_progress = True
      self.recording_state_changed.emit(False)
      self.message_requested.emit("Recording", "Stopping...", True)
      if not self._ctx.recording.request_stop():
        self._stop_in_progress = False
    except Exception as exc:
      self._stop_in_progress = False
      log.error("recording: failed to stop: %s", exc)
      self.message_requested.emit("Recording error", str(exc), False)

  def abort_if_recording(self) -> None:
    """Abort an in-flight recording without a result (used on shutdown)."""
    if self._ctx.recording.is_recording() and not self._stop_in_progress:
      try:
        self._ctx.recording.abort()
        log.info("recording: aborted on shutdown")
      except Exception:
        log.exception("recording: abort error on shutdown")

  @pyqtSlot(object)
  def _on_stop_finished(self, ts_path_obj: object) -> None:
    ts_path = Path(str(ts_path_obj))
    cfg = self._stop_cfg or RecordingConfig(output_dir=Path.home())
    rotation = self._ctx.recording_rotation
    self._ctx.recording_rotation = 0
    self._stop_in_progress = False
    self._stop_cfg = None

    # A rotation applied before recording is stored losslessly as a display
    # matrix flag, which MPEG-TS cannot carry. When auto-remux is on we produce
    # mp4; when it is off but a rotation is present we fall back to mkv (also
    # lossless and rotation-capable) instead of forcing an unwanted mp4.
    if cfg.auto_remux_to_mp4 or rotation:
      stderr_path = ts_path.with_suffix(".stderr.log") if log.isEnabledFor(logging.DEBUG) else None
      suffix = ".mp4" if cfg.auto_remux_to_mp4 else ".mkv"
      target_path = ts_path.with_suffix(suffix)
      arguments = [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
      ]
      if rotation:
        # -display_rotation is an input option (must precede -i). Its value is
        # counterclockwise, while mpv's video-rotate is clockwise, so negate it.
        # The deprecated `-metadata rotate=` tag is silently ignored by ffmpeg 7+.
        arguments += ["-display_rotation", str(-rotation)]
      arguments += [
        "-i",
        str(ts_path),
        "-map",
        "0:v:0?",
        "-map",
        "0:a?",
        "-sn",
        "-dn",
        "-c",
        "copy",
      ]
      if cfg.auto_remux_to_mp4:
        arguments += ["-movflags", "+faststart"]
      arguments += [str(target_path)]
      job = RemuxJob(
        source_path=ts_path,
        target_path=target_path,
        ffmpeg_path=cfg.ffmpeg_path,
        arguments=arguments,
        remove_source_on_success=True,
        stderr_path=stderr_path,
        kind="recording",
      )
      target_path = self._ctx.remux_queue.enqueue(job)
      log.info("recording: stopped output=%s remuxing=%s rotation=%s", ts_path, target_path, rotation)
      self.message_requested.emit("Recording stopped", f"Remuxing: {target_path.name}", True)
      return

    log.info("recording: stopped output=%s remuxed=%s", ts_path, False)
    self.message_requested.emit("Recording stopped", f"Saved: {ts_path.name}", False)

  @pyqtSlot(object)
  def _on_stop_failed(self, exc_obj: object) -> None:
    self._stop_in_progress = False
    self._stop_cfg = None
    log.error("recording: failed to stop: %s", exc_obj)
    self.message_requested.emit("Recording error", str(exc_obj), False)

  @pyqtSlot(object)
  def _on_remux_job_finished(self, result_obj: object) -> None:
    result = result_obj
    if not isinstance(result, FfmpegJobResult):
      return
    # Clip and snapshot jobs share this queue but are handled elsewhere.
    if result.job.kind != "recording":
      return

    if result.success:
      target = result.job.target_path
      container = target.suffix.lstrip(".").lower() or "file"
      log.info("recording: stopped output=%s remuxed=%s", target, True)
      self.message_requested.emit(
        "Recording stopped", f"Saved: {target.name} (remuxed to {container})", False
      )
      return

    if result.job.stderr_path is not None:
      log.warning(
        "recording: remux failed code=%s stderr_log=%s",
        result.exit_code,
        result.job.stderr_path,
      )
    else:
      log.warning("recording: remux failed code=%s", result.exit_code)
    log.info("recording: stopped output=%s remuxed=%s", result.job.source_path, False)
    self.message_requested.emit(
      "Recording stopped", f"Saved: {result.job.source_path.name}", False
    )
