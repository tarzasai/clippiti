"""Main PyQt application shell and composition root."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sys
import logging
from copy import deepcopy
from typing import TYPE_CHECKING

from pathlib import Path as _Path

from PyQt6.QtCore import QObject, QStandardPaths, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QIcon, QKeyEvent, QPixmap, QResizeEvent
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox
import os

from .clip_dialog import ClipWorkflow
from .control_strip import ControlStrip
from ..services.favicons import get_favicon
from .osd import OsdOverlay
from .settings_dialog import SettingsDialog
from .video_surface import VideoSurface
from ..model.config import ensure_output_dirs, normalize_config, save_config
from ..services.clipper import ClipConfig, ClipService
from ..services.recording import AsyncRecordingService, RecordingConfig
from ..services.remux_queue import FfmpegJobResult, RemuxJob, RemuxQueueService
from ..services.snapshot import SnapshotConfig, SnapshotService

if TYPE_CHECKING:
  from ..services.buffer_engine import SessionRuntime

log = logging.getLogger("clippiti")


@dataclass
class AppRunResult:
  exit_code: int
  startup_result: object | None = None


class FaviconWorker(QObject):
  finished = pyqtSignal(object)  # bytes | None

  def __init__(self, url: str, plugin: str) -> None:
    super().__init__()
    self._url = url
    self._plugin = plugin

  @pyqtSlot()
  def run(self) -> None:
    cache_dir = _Path(QStandardPaths.writableLocation(
      QStandardPaths.StandardLocation.CacheLocation
    ))
    log.debug("favicon worker: url=%s plugin=%s cache_dir=%s", self._url, self._plugin, cache_dir)
    data = get_favicon(self._url, self._plugin, cache_dir, size=32)
    log.debug("favicon worker: result=%s", "bytes(%d)" % len(data) if isinstance(data, bytes) else None)
    self.finished.emit(data)


class StartupWorker(QObject):
  finished = pyqtSignal(object)
  failed = pyqtSignal(object)

  def __init__(self, startup_task: Callable[[], object]) -> None:
    super().__init__()
    self._startup_task = startup_task

  @pyqtSlot()
  def run(self) -> None:
    try:
      result = self._startup_task()
    except Exception as exc:
      self.failed.emit(exc)
      return
    self.finished.emit(result)


_HELP_TEXT = (
  "<table cellspacing='0' cellpadding='2'>"
  "<tr><td align='center' style='padding-right: 20px;'>H</td><td>This help screen</td></tr>"
  "<tr><td align='center' style='padding-right: 20px;'>S</td><td>Snapshot</td></tr>"
  "<tr><td align='center' style='padding-right: 20px;'>C</td><td>Make a clip</td></tr>"
  "<tr><td align='center' style='padding-right: 20px;'>R</td><td>Start / stop recording</td></tr>"
  "<tr><td align='center' style='padding-right: 20px;'>M</td><td>Mute / Unmute</td></tr>"
  "<tr><td align='center' style='padding-right: 20px;'>O</td><td>Rotate video +90\N{DEGREE SIGN} clockwise</td></tr>"
  "<tr><td align='center' style='padding-right: 20px;'>F</td><td>Flip video horizontally</td></tr>"
  "<tr><td align='center' style='padding-right: 20px;'>P</td><td>Pin / Unpin toolbar</td></tr>"
  "<tr><td align='center' style='padding-right: 20px;'>T</td><td>Next toolbar position (Shift+T to go back)</td></tr>"
  "<tr><td align='center' style='padding-right: 20px;'>K</td><td>Settings</td></tr>"
  "<tr><td align='center' style='padding-right: 20px;'>+/-</td><td>Volume up / down (also PgUp/PgDn or mouse wheel)</td></tr>"
  "</table>"
)

ICON_PATH = Path(__file__).parent.parent / "resources" / "icons" / "app-icon.png"


class MainWindow(QMainWindow):

  def __init__(
    self,
    media_source: str | None,
    mpv_options: dict[str, object],
    trigger_radius: int,
    resize_debounce_ms: int,
    clip_cfg: ClipConfig | None = None,
    recording_cfg: RecordingConfig | None = None,
    config: dict[str, object] | None = None,
    config_path: Path | None = None,
  ) -> None:
    super().__init__()
    self.setWindowTitle("Clippiti Player")
    self.resize(1280, 760)

    self._shutting_down = False
    self._runtime = None
    self._config = normalize_config(deepcopy(config) if config is not None else {})
    self._config_path = config_path
    self._recording = AsyncRecordingService(self)
    self._recording.stop_finished.connect(self._handle_recording_stopped)
    self._recording.stop_failed.connect(self._handle_recording_stop_failed)
    self._remux_service = RemuxQueueService(self)
    self._remux_service.job_finished.connect(self._on_remux_job_finished)
    self._clip_cfg = clip_cfg
    self._clip_service = ClipService(clip_cfg) if clip_cfg is not None else None
    self._clip_workflow: ClipWorkflow | None = None
    self._recording_cfg = recording_cfg
    self._recording_rotation = 0
    self._snapshot_service = SnapshotService(self._build_snapshot_cfg(self._config), self)
    self._snapshot_service.snapshot_ready.connect(self._on_snapshot_ready)
    self._snapshot_service.snapshot_failed.connect(self._on_snapshot_failed)
    self._stop_in_progress = False
    self._stop_cfg: RecordingConfig | None = None
    self._offline_close_pending = False
    self.video = VideoSurface(media_source, mpv_options)
    self.setCentralWidget(self.video)

    self.osd = OsdOverlay(self.video)
    if not media_source:
      self.osd.show_message("loading stream", persistent=True)

    self.strip = ControlStrip(
      self.video,
      trigger_radius,
    )
    self.strip.raise_()
    self._wire_toolbar_actions()
    self._apply_audio_state()

    self._reposition_timer = QTimer(self)
    self._reposition_timer.setSingleShot(True)
    self._reposition_timer.setInterval(max(0, int(resize_debounce_ms)))
    self._reposition_timer.timeout.connect(self.strip.reposition)

    self._pipeline_watch_timer = QTimer(self)
    self._pipeline_watch_timer.setSingleShot(False)
    self._pipeline_watch_timer.setInterval(1000)
    self._pipeline_watch_timer.timeout.connect(self._check_pipeline_health)

    self._apply_runtime_config(self._config, persist=False)

    self._favicon_thread: QThread | None = None
    self._favicon_worker: FaviconWorker | None = None

    self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    self.video.setFocus()

  def shutdown(self) -> None:
    if self._shutting_down:
      return
    self._shutting_down = True
    log.debug("window: shutdown begin")
    self._reposition_timer.stop()
    self._pipeline_watch_timer.stop()
    if self._recording.is_recording() and not self._stop_in_progress:
      try:
        self._recording.abort()
        log.info("recording: aborted on shutdown")
      except Exception:
        log.exception("recording: abort error on shutdown")
    self._remux_service.shutdown()
    self._recording.shutdown()
    self._snapshot_service.shutdown()
    self.strip.shutdown()
    self.video.shutdown()
    if self._favicon_thread is not None and self._favicon_thread.isRunning():
      self._favicon_thread.quit()
      self._favicon_thread.wait(1000)
    log.info("window: shutdown complete")

  def set_stream_icon(self, url: str, plugin: str) -> None:
    thread = QThread(self)
    worker = FaviconWorker(url, plugin)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(self._on_favicon_ready)
    worker.finished.connect(thread.quit)
    self._favicon_thread = thread
    self._favicon_worker = worker  # prevent GC before thread starts
    thread.start()

  @pyqtSlot(object)
  def _on_favicon_ready(self, data: object) -> None:
    if not isinstance(data, bytes) or self._shutting_down:
      return
    pixmap = QPixmap()
    if pixmap.loadFromData(data):
      self.setWindowIcon(QIcon(pixmap))

  def set_window_title(self, title: str) -> None:
    self.setWindowTitle(title)

  def set_media_source(self, media_source: str) -> None:
    self.video.set_media_source(media_source)
    self._apply_audio_state()
    self.osd.clear_message()

  def set_runtime(self, runtime: SessionRuntime) -> None:
    self._runtime = runtime
    self._offline_close_pending = False
    if not self._pipeline_watch_timer.isActive():
      self._pipeline_watch_timer.start()

  def _check_pipeline_health(self) -> None:
    if self._shutting_down or self._runtime is None:
      return
    if self._offline_close_pending:
      return

    streamlink_pump = getattr(self._runtime, "stream_pump", None)
    ffmpeg_proc = getattr(self._runtime, "ffmpeg_proc", None)
    streamlink_terminated = self._is_terminated(streamlink_pump)
    ffmpeg_terminated = self._is_terminated(ffmpeg_proc)
    if not (streamlink_terminated or ffmpeg_terminated):
      return

    self._offline_close_pending = True
    streamlink_code = self._poll_code(streamlink_pump)
    ffmpeg_code = self._poll_code(ffmpeg_proc)
    log.warning(
      "pipeline terminated: stream_pump_exit=%s ffmpeg_exit=%s; closing window",
      streamlink_code,
      ffmpeg_code,
    )
    self.osd.show_message("Stream offline", "Pipeline terminated; closing...", persistent=True)
    QTimer.singleShot(900, self.close)

  @staticmethod
  def _is_terminated(proc: object | None) -> bool:
    if proc is None:
      return False
    poll = getattr(proc, "poll", None)
    if not callable(poll):
      return False
    return poll() is not None

  @staticmethod
  def _poll_code(proc: object | None) -> int | None:
    if proc is None:
      return None
    poll = getattr(proc, "poll", None)
    if not callable(poll):
      return None
    try:
      return poll()
    except Exception:
      return None

  def _wire_toolbar_actions(self) -> None:
    self.strip.mute_action.triggered.connect(self._mute_action)
    self.strip.record_action.triggered.connect(self._toggle_recording)
    self.strip.clip_action.triggered.connect(self._clip_action)
    self.strip.snapshot_action.triggered.connect(self._snapshot_action)
    self.strip.rotate_action.triggered.connect(self._rotate_action)
    self.strip.flip_action.triggered.connect(self._flip_action)
    self.strip.move_action.triggered.connect(self._move_toolbar_action)
    self.strip.settings_action.triggered.connect(self._settings_action)

  def _show_osd_message(self, title: str, detail: str | None, persistent: bool) -> None:
    self.osd.show_message(title, detail, persistent=persistent)

  def _clear_osd_message(self) -> None:
    self.osd.clear_message()

  def _is_player_muted(self) -> bool:
    return self.video.muted

  def _set_player_muted(self, muted: bool) -> None:
    self.video.muted = muted
    self._apply_audio_state()

  def _rebuild_clip_workflow(self) -> None:
    if self._clip_service is None or self._clip_cfg is None:
      self._clip_workflow = None
      return
    self._clip_workflow = ClipWorkflow(
      clip_service=self._clip_service,
      clip_cfg=self._clip_cfg,
      enqueue_job=self._remux_service.enqueue,
      show_message=self._show_osd_message,
      clear_message=self._clear_osd_message,
      is_player_muted=self._is_player_muted,
      set_player_muted=self._set_player_muted,
      parent=self,
    )

  def _mute_action(self) -> None:
    self.video.muted = not self.video.muted
    self._apply_audio_state()
    self.osd.show_message(self._volume_osd_title())

  def _snapshot_action(self) -> None:
    if self._runtime is None or self.video.player is None:
      self.osd.show_message("Snapshot", "Not ready yet")
      return
    rotation = self.video.current_rotation()
    lag = self.video.live_lag_seconds() or 0.0
    if not self._snapshot_service.capture(self._runtime, lag, rotation):
      self.osd.show_message("Snapshot", "Failed to queue")

  @pyqtSlot(str)
  def _on_snapshot_ready(self, target_path: str) -> None:
    self.osd.show_snapshot_preview(target_path, timeout_ms=2000)

  @pyqtSlot(str)
  def _on_snapshot_failed(self, error: str) -> None:
    detail = error.strip() if error else "save failed"
    self.osd.show_message("Snapshot", detail)

  def _rotate_action(self) -> None:
    if self.video.player is None:
      self.osd.show_message("Rotate", "Player not ready yet")
      return
    if self._recording.is_recording():
      self.osd.show_message("Rotate", "Disabled while recording")
      return
    rotation = self.video.rotate_clockwise()
    self.osd.show_message("Rotate", f"{rotation}\N{DEGREE SIGN}")

  def _flip_action(self) -> None:
    if self.video.player is None:
      self.osd.show_message("Flip", "Player not ready yet")
      return
    if self.video.toggle_flip_horizontal():
      self.osd.show_message("Flip", "Toggled")
    else:
      self.osd.show_message("Flip", "Failed")

  def _move_toolbar_action(self) -> None:
    mods = QApplication.keyboardModifiers()
    step = -1 if mods & Qt.KeyboardModifier.ControlModifier else 1
    self.strip.move_position(step)

  def _apply_audio_state(self) -> None:
    self.strip.set_audio_ui_state(self.video.volume, self.video.muted)

  def _adjust_volume(self, delta: int) -> bool:
    new_volume = max(0, min(100, self.video.volume + delta))
    if new_volume == self.video.volume:
      return False
    self.video.volume = new_volume
    if self.video.volume > 0 and self.video.muted:
      self.video.muted = False
    self._apply_audio_state()
    self.osd.show_message(self._volume_osd_title())
    return True

  def _volume_osd_title(self) -> str:
    if self.video.muted or self.video.volume <= 0:
      return "Muted"
    return f"volume {self.video.volume}%"

  def _toggle_recording(self) -> None:
    if self._recording.is_recording():
      self._stop_recording()
    else:
      self._start_recording()

  def _start_recording(self) -> None:
    if self._runtime is None:
      self.osd.show_message("Recording", "Stream not ready yet")
      return
    if self._recording_cfg is None:
      self.osd.show_message("Recording", "Recording not configured")
      return
    try:
      path = self._recording.start(self._runtime, self._recording_cfg)
      self._recording_rotation = self.video.current_rotation()
      log.info("recording: started output=%s", path)
      self.osd.show_message("Recording", f"Saving to {path.name}")
      self.strip.set_recording(True)
    except Exception as exc:
      log.error("recording: failed to start: %s", exc)
      self.osd.show_message("Recording failed", str(exc))

  def _stop_recording(self) -> None:
    if self._stop_in_progress:
      return

    try:
      cfg = self._recording_cfg or RecordingConfig(output_dir=Path.home())
      self._stop_cfg = cfg
      self._stop_in_progress = True
      self.strip.set_recording(False)
      self.osd.show_message("Recording", "Stopping...", persistent=True)
      if not self._recording.request_stop():
        self._stop_in_progress = False
    except Exception as exc:
      self._stop_in_progress = False
      log.error("recording: failed to stop: %s", exc)
      self.osd.show_message("Recording error", str(exc))

  @pyqtSlot(object)
  def _handle_recording_stopped(self, ts_path_obj: object) -> None:
    ts_path = Path(str(ts_path_obj))
    cfg = self._stop_cfg or RecordingConfig(output_dir=Path.home())
    rotation = self._recording_rotation
    self._recording_rotation = 0
    self._stop_in_progress = False
    self._stop_cfg = None

    # A rotation applied before recording is stored losslessly as a display
    # matrix flag, which requires an mp4/mov container, so a rotated recording
    # is always remuxed to mp4 even when auto-remux is off.
    if cfg.auto_remux_to_mp4 or rotation:
      stderr_path = ts_path.with_suffix(".stderr.log") if log.isEnabledFor(logging.DEBUG) else None
      target_path = ts_path.with_suffix(".mp4")
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
        "-movflags",
        "+faststart",
        str(target_path),
      ]
      job = RemuxJob(
        source_path=ts_path,
        target_path=target_path,
        ffmpeg_path=cfg.ffmpeg_path,
        arguments=arguments,
        remove_source_on_success=True,
        stderr_path=stderr_path,
        kind="recording",
      )
      target_path = self._remux_service.enqueue(job)
      log.info("recording: stopped output=%s remuxing=%s rotation=%s", ts_path, target_path, rotation)
      self.osd.show_message("Recording stopped", f"Remuxing: {target_path.name}", persistent=True)
      return

    log.info("recording: stopped output=%s remuxed=%s", ts_path, False)
    self.osd.show_message("Recording stopped", f"Saved: {ts_path.name}")

  @pyqtSlot(object)
  def _handle_recording_stop_failed(self, exc_obj: object) -> None:
    self._stop_in_progress = False
    self._stop_cfg = None
    log.error("recording: failed to stop: %s", exc_obj)
    self.osd.show_message("Recording error", str(exc_obj))

  @pyqtSlot(object)
  def _on_remux_job_finished(self, result_obj: object) -> None:
    result = result_obj
    if not isinstance(result, FfmpegJobResult):
      return

    if result.job.kind == "clip":
      if self._clip_workflow is not None:
        self._clip_workflow.handle_clip_job_finished(result)
      return

    if result.success:
      log.info("recording: stopped output=%s remuxed=%s", result.job.target_path, True)
      self.osd.show_message("Recording stopped", f"Saved: {result.job.target_path.name} (remuxed to mp4)")
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
    self.osd.show_message("Recording stopped", f"Saved: {result.job.source_path.name}")

  def _clip_action(self) -> None:
    if self._runtime is None:
      self.osd.show_message("Clip", "Stream not ready yet")
      return
    if self._clip_workflow is None:
      self.osd.show_message("Clip", "Clip service not configured")
      return
    self._clip_workflow.run_clip_dialog(self._runtime, self)

  def _settings_action(self) -> None:
    dialog = SettingsDialog(self._config, self)
    if dialog.exec() != dialog.DialogCode.Accepted:
      return

    try:
      updated = dialog.updated_config()
    except Exception as exc:
      QMessageBox.warning(self, "Invalid settings", str(exc))
      self.osd.show_message("Settings", "Invalid settings")
      return

    restart_required = self._restart_required(self._config, updated)

    try:
      self._apply_runtime_config(updated, persist=True)
    except Exception as exc:
      log.error("settings: failed to apply: %s", exc)
      QMessageBox.warning(self, "Settings", f"Failed to apply settings: {exc}")
      self.osd.show_message("Settings", "Apply failed")
      return

    self.osd.show_message("Settings", "Saved")
    if restart_required:
      QMessageBox.information(
        self,
        "Relaunch required",
        "Some changes affect startup-only settings. Please relaunch Clippiti to apply them fully.",
      )

  def _apply_runtime_config(self, config: dict[str, object], persist: bool) -> None:
    normalized = normalize_config(config)
    ensure_output_dirs(normalized)

    general = normalized["general"]
    recording = normalized["recording"]
    clip = normalized["clip"]

    ffmpeg_path = str(general.get("ffmpeg_path", "ffmpeg"))

    self._recording_cfg = RecordingConfig(
      output_dir=Path(str(recording.get("dir", "~/Videos/Clippiti/recordings"))).expanduser(),
      filename_format=str(recording.get("filename_format", "{author}.{timestamp}")),
      ffmpeg_path=ffmpeg_path,
      auto_remux_to_mp4=bool(recording.get("auto_remux_to_mp4", False)),
    )

    self._clip_cfg = ClipConfig(
      output_dir=Path(str(clip.get("dir", "~/Videos/Clippiti/clips"))).expanduser(),
      ffmpeg_path=ffmpeg_path,
      default_duration=int(clip.get("default_duration", 30)),
      filename_format=str(clip.get("filename_format", "{author}.{timestamp}")),
    )
    self._clip_service = ClipService(self._clip_cfg)
    self._rebuild_clip_workflow()

    self._snapshot_service.set_config(self._build_snapshot_cfg(normalized))

    self.strip.set_trigger_radius(int(general.get("controls_area", 300)))
    self.strip.set_position(str(general.get("controls_position", "bottom-right-vertical")))
    self._reposition_timer.setInterval(max(0, int(general.get("controls_resize_debounce_ms", 40))))

    self._config = normalized
    if persist and self._config_path is not None:
      save_config(self._config_path, normalized)

  @staticmethod
  def _restart_required(before: dict[str, object], after: dict[str, object]) -> bool:
    restart_paths = [
      ("general", "segment_seconds"),
      ("general", "window_segments"),
      ("general", "mpv_options"),
      ("streamlink", "default_args"),
    ]

    for section, key in restart_paths:
      before_section = before.get(section, {})
      after_section = after.get(section, {})
      before_value = before_section.get(key) if isinstance(before_section, dict) else None
      after_value = after_section.get(key) if isinstance(after_section, dict) else None
      if before_value != after_value:
        return True
    return False

  @staticmethod
  def _build_snapshot_cfg(config: dict[str, object]) -> SnapshotConfig:
    general = config.get("general", {}) if isinstance(config.get("general"), dict) else {}
    snapshot = config.get("snapshot", {}) if isinstance(config.get("snapshot"), dict) else {}
    return SnapshotConfig(
      output_dir=Path(str(snapshot.get("dir", "~/Pictures/Clippiti/snapshots"))).expanduser(),
      ffmpeg_path=str(general.get("ffmpeg_path", "ffmpeg")),
      filename_format=str(snapshot.get("filename_format", "{author}.{timestamp}")),
    )

  @staticmethod
  def _safe_filename(name: str) -> str:
    keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ")
    return "".join(ch if ch in keep else "_" for ch in name).strip("_").replace(" ", "_")

  def closeEvent(self, event) -> None:  # noqa: N802
    self.shutdown()
    super().closeEvent(event)

  def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
    super().resizeEvent(event)
    self._reposition_timer.start()

  def handle_volume_wheel(self, delta_y: int) -> bool:
    if delta_y > 0:
      return self._adjust_volume(5)
    if delta_y < 0:
      return self._adjust_volume(-5)
    return False

  def handle_volume_key(self, key: int) -> bool:
    if key in (Qt.Key.Key_Minus, Qt.Key.Key_PageDown):
      return self._adjust_volume(-5)
    if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_PageUp):
      return self._adjust_volume(5)
    return False

  def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
    key = event.key()
    mods = event.modifiers()

    if key == Qt.Key.Key_H:
      if self.osd.isVisible():
        self.osd.clear_message()
      else:
        self.osd.show_message("keyboard shortcuts", _HELP_TEXT, persistent=True)
      event.accept()
      return

    if key == Qt.Key.Key_K:
      self._settings_action()
      event.accept()
      return

    if key == Qt.Key.Key_S:
      self._snapshot_action()
      event.accept()
      return

    if key == Qt.Key.Key_C:
      self._clip_action()
      event.accept()
      return

    if key == Qt.Key.Key_R:
      self._toggle_recording()
      event.accept()
      return

    if key == Qt.Key.Key_M:
      self._mute_action()
      event.accept()
      return

    if key == Qt.Key.Key_P:
      pinned = self.strip.toggle_pin()
      self.osd.show_message("toolbar pinned" if pinned else "toolbar unpinned")
      event.accept()
      return

    if key == Qt.Key.Key_T:
      step = -1 if mods & Qt.KeyboardModifier.ShiftModifier else 1
      self.strip.move_position(step)
      event.accept()
      return

    if self.handle_volume_key(key):
      event.accept()
      return

    super().keyPressEvent(event)


def run_app(
  media_source: str | None,
  mpv_options: dict[str, object],
  trigger_radius: int,
  resize_debounce_ms: int,
  window_title: str | None = None,
  clip_cfg: ClipConfig | None = None,
  recording_cfg: RecordingConfig | None = None,
  config: dict[str, object] | None = None,
  config_path: Path | None = None,
  startup_task: Callable[[], object] | None = None,
  on_startup_ready: Callable[[MainWindow, object], None] | None = None,
  on_startup_failed: Callable[[Exception], None] | None = None,
  on_startup_cancel: Callable[[], None] | None = None,
) -> AppRunResult:
  app = QApplication(sys.argv)
  app.setApplicationName('Clippiti')
  app.setWindowIcon(QIcon(str(ICON_PATH)))
  try:
    app.setDesktopFileName('clippiti.desktop')  # Linux integration
  except Exception:
    pass  # Older Qt bindings or platforms may not support this; ignore safely.
  app.setQuitOnLastWindowClosed(True)
  window = MainWindow(
    media_source,
    mpv_options,
    trigger_radius,
    resize_debounce_ms,
    clip_cfg=clip_cfg,
    recording_cfg=recording_cfg,
    config=config,
    config_path=config_path,
  )
  if window_title:
    window.set_window_title(window_title)
  startup_result = None
  startup_thread = None
  startup_worker = None
  startup_completed = startup_task is None

  app.aboutToQuit.connect(window.shutdown)

  if startup_task is not None:
    startup_thread = QThread(app)
    startup_worker = StartupWorker(startup_task)
    startup_worker.moveToThread(startup_thread)
    startup_thread.started.connect(startup_worker.run)

    def handle_startup_success(result: object) -> None:
      nonlocal startup_result, startup_completed
      startup_result = result
      startup_completed = True
      if on_startup_ready is not None:
        on_startup_ready(window, result)
      startup_thread.quit()

    def handle_startup_failure(exc: Exception) -> None:
      nonlocal startup_completed
      startup_completed = True
      if on_startup_failed is not None:
        on_startup_failed(exc)
      startup_thread.quit()
      app.exit(3)

    def request_startup_cancel() -> None:
      if not startup_completed and on_startup_cancel is not None:
        on_startup_cancel()

    startup_worker.finished.connect(handle_startup_success)
    startup_worker.failed.connect(handle_startup_failure)
    app.aboutToQuit.connect(request_startup_cancel)

  window.show()
  if startup_thread is not None:
    startup_thread.start()
  log.debug("app: event loop enter")
  exit_code = app.exec()

  if startup_thread is not None:
    startup_thread.quit()
    startup_thread.wait(5000)

  return AppRunResult(exit_code=exit_code, startup_result=startup_result)
