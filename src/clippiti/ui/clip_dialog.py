"""Clip range dialog with static frame previews and optional video preview."""

from collections.abc import Callable
from pathlib import Path
import logging

from PyQt6.QtCore import QEventLoop, QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedLayout, QVBoxLayout, QWidget

from ..services.clipper import ClipBufferStage, ClipConfig, ClipExportContext, ClipService
from ..services.remux_queue import FfmpegJob, FfmpegJobResult


log = logging.getLogger("clippiti")


class _TaskWorker(QObject):
  finished = pyqtSignal(object)
  failed = pyqtSignal(object)

  def __init__(self, task: Callable[[], object]) -> None:
    super().__init__()
    self._task = task

  @pyqtSlot()
  def run(self) -> None:
    try:
      result = self._task()
    except Exception as exc:
      self.failed.emit(exc)
      return
    self.finished.emit(result)


class _RangeSlider(QWidget):
  valueChanged = pyqtSignal(int, int)

  def __init__(self, parent=None):
    super().__init__(parent)
    self._minimum = 0
    self._maximum = 60
    self._lower = 0
    self._upper = 60
    self._min_span = 5
    self._handle_radius = 8
    self._active_handle: str | None = None
    self.setMinimumHeight(36)
    self.setMaximumHeight(36)
    self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    self.setMouseTracking(True)

  def setRange(self, minimum: int, maximum: int) -> None:
    self._minimum = minimum
    self._maximum = max(minimum + self._min_span, maximum)
    self._lower = max(self._minimum, min(self._lower, self._maximum - self._min_span))
    self._upper = max(self._lower + self._min_span, min(self._upper, self._maximum))
    self.update()

  def setValues(self, lower: int, upper: int) -> None:
    bounded_lower = max(self._minimum, min(lower, self._maximum - self._min_span))
    bounded_upper = max(bounded_lower + self._min_span, min(upper, self._maximum))
    if bounded_lower == self._lower and bounded_upper == self._upper:
      return
    self._lower = bounded_lower
    self._upper = bounded_upper
    self.valueChanged.emit(self._lower, self._upper)
    self.update()

  def setMinSpan(self, span: int) -> None:
    self._min_span = max(1, span)
    self.setValues(self._lower, self._upper)

  def values(self) -> tuple[int, int]:
    return self._lower, self._upper

  def _groove_bounds(self) -> tuple[int, int, int]:
    left = self._handle_radius + 4
    right = self.width() - self._handle_radius - 4
    y = self.height() // 2
    if right <= left:
      right = left + 1
    return left, right, y

  def _value_to_x(self, value: int) -> int:
    left, right, _ = self._groove_bounds()
    if self._maximum == self._minimum:
      return left
    ratio = (value - self._minimum) / (self._maximum - self._minimum)
    return int(left + ratio * (right - left))

  def _x_to_value(self, x: int) -> int:
    left, right, _ = self._groove_bounds()
    if right == left:
      return self._minimum
    ratio = (x - left) / (right - left)
    ratio = max(0.0, min(1.0, ratio))
    return int(round(self._minimum + ratio * (self._maximum - self._minimum)))

  def paintEvent(self, _event) -> None:
    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    left, right, y = self._groove_bounds()
    lower_x = self._value_to_x(self._lower)
    upper_x = self._value_to_x(self._upper)

    painter.setPen(QPen(QColor("#767676"), 4))
    painter.drawLine(left, y, right, y)

    painter.setPen(QPen(QColor("#aaaaaa"), 1))
    for second in range(self._minimum, self._maximum + 1):
      tick_x = self._value_to_x(second)
      painter.drawLine(tick_x, y - 6, tick_x, y + 6)

    painter.setPen(QPen(QColor("#2f89fc"), 6))
    painter.drawLine(lower_x, y, upper_x, y)

    painter.setPen(QPen(QColor("#3a3a3a"), 1))
    painter.setBrush(QBrush(QColor("#f2f2f2")))
    painter.drawEllipse(lower_x - self._handle_radius, y - self._handle_radius, self._handle_radius * 2, self._handle_radius * 2)
    painter.drawEllipse(upper_x - self._handle_radius, y - self._handle_radius, self._handle_radius * 2, self._handle_radius * 2)

  def mousePressEvent(self, event) -> None:
    x = event.position().x()
    lower_x = self._value_to_x(self._lower)
    upper_x = self._value_to_x(self._upper)
    self._active_handle = "lower" if abs(x - lower_x) <= abs(x - upper_x) else "upper"
    self._move_active_handle(int(x))

  def mouseMoveEvent(self, event) -> None:
    if self._active_handle is None:
      return
    self._move_active_handle(int(event.position().x()))

  def mouseReleaseEvent(self, _event) -> None:
    self._active_handle = None

  def _move_active_handle(self, x: int) -> None:
    value = self._x_to_value(x)
    if self._active_handle == "lower":
      self.setValues(value, self._upper)
    elif self._active_handle == "upper":
      self.setValues(self._lower, value)


class ClipRangeDialog(QDialog):
  MIN_DURATION = 5

  def __init__(self, stream_author: str, stream_category: str, parent=None):
    super().__init__(parent)
    self.setWindowTitle(f"Clipping: {stream_author} - {stream_category}")
    self.resize(1000, 500)
    self._start_preview_image: Path | None = None
    self._end_preview_image: Path | None = None
    self._video_source_path: Path | None = None
    self._video_visible = False
    self._pending_preview_start_ms: int | None = None

    self._duration_label = QLabel("")
    self._start_label = QLabel("Start: 0s")
    self._end_label = QLabel("End: 5s")
    for label in (self._duration_label, self._start_label, self._end_label):
      label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    labels_layout = QHBoxLayout()
    labels_layout.addWidget(self._start_label, 0, Qt.AlignmentFlag.AlignLeft)
    labels_layout.addStretch(1)
    labels_layout.addWidget(self._duration_label, 0, Qt.AlignmentFlag.AlignHCenter)
    labels_layout.addStretch(1)
    labels_layout.addWidget(self._end_label, 0, Qt.AlignmentFlag.AlignRight)

    self._range_slider = _RangeSlider()
    self._range_slider.setMinSpan(self.MIN_DURATION)
    self._range_slider.valueChanged.connect(self._sync_labels)

    self._start_preview = QLabel("Start preview unavailable")
    self._end_preview = QLabel("End preview unavailable")
    for preview in (self._start_preview, self._end_preview):
      preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
      preview.setMinimumSize(220, 120)
      preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
      preview.setStyleSheet("border: 1px solid #666;")

    previews_layout = QGridLayout()
    previews_layout.setContentsMargins(0, 0, 0, 0)
    previews_layout.addWidget(QLabel("Start frame"), 0, 0)
    previews_layout.addWidget(QLabel("End frame"), 0, 1)
    previews_layout.addWidget(self._start_preview, 1, 0)
    previews_layout.addWidget(self._end_preview, 1, 1)
    previews_layout.setColumnStretch(0, 1)
    previews_layout.setColumnStretch(1, 1)

    slider_layout = QVBoxLayout()
    slider_layout.setContentsMargins(0, 0, 0, 0)
    slider_layout.addLayout(previews_layout)
    slider_layout.addLayout(labels_layout)
    slider_layout.addWidget(self._range_slider)

    self._selection_widget = QWidget()
    self._selection_widget.setContentsMargins(0, 0, 0, 0)
    self._selection_widget.setLayout(slider_layout)

    self._video_widget = QVideoWidget()
    self._video_widget.setMinimumHeight(220)
    self._video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    self._player = QMediaPlayer(self)
    self._audio_output = QAudioOutput(self)
    self._player.setAudioOutput(self._audio_output)
    self._player.setVideoOutput(self._video_widget)
    self._audio_output.setVolume(0.5)
    self._player.positionChanged.connect(self._loop_selection_if_needed)
    self._player.mediaStatusChanged.connect(self._on_media_status_changed)

    self._content_stack = QStackedLayout()
    self._content_stack.setContentsMargins(0, 0, 0, 0)
    self._content_stack.setSpacing(10)
    self._content_stack.addWidget(self._selection_widget)
    self._content_stack.addWidget(self._video_widget)

    content_widget = QWidget()
    content_widget.setLayout(self._content_stack)

    self._toggle_video_button = QPushButton("Show video preview")
    self._toggle_video_button.setFixedHeight(32)
    self._toggle_video_button.clicked.connect(self._toggle_video_preview)

    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.setContentsMargins(0, 0, 0, 0)
    buttons.setMinimumHeight(32)
    buttons.setFixedHeight(32)
    for button in buttons.buttons():
      button.setMinimumHeight(32)
      button.setFixedHeight(32)
    buttons.accepted.connect(self.accept)
    buttons.rejected.connect(self.reject)

    bottom_layout = QHBoxLayout()
    bottom_layout.setContentsMargins(0, 0, 0, 0)
    bottom_layout.addWidget(self._toggle_video_button, 0, Qt.AlignmentFlag.AlignLeft)
    bottom_layout.addStretch(1)
    bottom_layout.addWidget(buttons)

    bottom_bar = QWidget()
    bottom_bar.setMinimumHeight(32)
    bottom_bar.setFixedHeight(32)
    bottom_bar.setLayout(bottom_layout)

    layout = QVBoxLayout()
    layout.addWidget(content_widget)
    layout.addWidget(bottom_bar)
    self.setLayout(layout)

    self.set_timeline_max(60)

  def set_timeline_max(self, timeline_seconds: int) -> None:
    max_seconds = max(self.MIN_DURATION, timeline_seconds)
    self._range_slider.setRange(0, max_seconds)
    self._range_slider.setValues(0, max_seconds)
    self._sync_labels()

  def set_selected_range(self, start_seconds: int, end_seconds: int) -> None:
    self._range_slider.setValues(start_seconds, end_seconds)
    self._sync_labels()

  def on_range_changed(self, callback) -> None:
    self._range_slider.valueChanged.connect(lambda _start, _end: callback())

  def selected_range(self) -> tuple[int, int]:
    return self._range_slider.values()

  def set_video_source(self, video_path: Path | None) -> None:
    self._video_source_path = video_path
    if video_path is None or not video_path.exists():
      self._player.stop()
      self._player.setSource(QUrl())
      return
    if self._video_visible:
      self._load_video_source(video_path)
      self._seek_to_start()
      self._player.play()

  def set_preview_images(self, start_image: Path | None, end_image: Path | None) -> None:
    self._start_preview_image = start_image
    self._end_preview_image = end_image
    self._set_preview(self._start_preview, start_image, "Start preview unavailable")
    self._set_preview(self._end_preview, end_image, "End preview unavailable")

  def resizeEvent(self, event) -> None:
    super().resizeEvent(event)
    self._set_preview(self._start_preview, self._start_preview_image, "Start preview unavailable")
    self._set_preview(self._end_preview, self._end_preview_image, "End preview unavailable")

  def showEvent(self, event) -> None:
    super().showEvent(event)
    self._set_preview(self._start_preview, self._start_preview_image, "Start preview unavailable")
    self._set_preview(self._end_preview, self._end_preview_image, "End preview unavailable")

  def _set_preview(self, label: QLabel, image_path: Path | None, fallback_text: str) -> None:
    if image_path is None or not image_path.exists():
      label.setPixmap(QPixmap())
      label.setText(fallback_text)
      return
    pixmap = QPixmap(str(image_path))
    if pixmap.isNull():
      label.setPixmap(QPixmap())
      label.setText(fallback_text)
      return
    scaled = pixmap.scaled(
      label.size(),
      Qt.AspectRatioMode.KeepAspectRatio,
      Qt.TransformationMode.SmoothTransformation,
    )
    label.setPixmap(scaled)
    label.setText("")

  def _sync_labels(self, *_args) -> None:
    start, end = self._range_slider.values()
    self._start_label.setText(f"Start: {start}s")
    self._end_label.setText(f"End: {end}s")
    self._duration_label.setText(f"Selected duration: {end - start}s")
    if self._video_visible:
      self._seek_to_start()

  def _seek_to_start(self) -> None:
    start, _ = self._range_slider.values()
    start_ms = int(start * 1000)
    self._pending_preview_start_ms = start_ms
    self._player.setPosition(start_ms)

  def _toggle_video_preview(self) -> None:
    self._video_visible = not self._video_visible
    if self._video_visible:
      self._content_stack.setCurrentWidget(self._video_widget)
      self._toggle_video_button.setText("Hide video preview")
      if self._video_source_path is not None and self._video_source_path.exists():
        self._load_video_source(self._video_source_path)
        self._seek_to_start()
        self._player.play()
    else:
      self._content_stack.setCurrentWidget(self._selection_widget)
      self._toggle_video_button.setText("Show video preview")
      self._pending_preview_start_ms = None
      self._player.pause()

  def _load_video_source(self, video_path: Path) -> None:
    current_source = self._player.source().toLocalFile()
    target_source = str(video_path)
    if current_source == target_source:
      return
    self._player.stop()
    self._player.setSource(QUrl.fromLocalFile(target_source))

  def done(self, result: int) -> None:
    self._pending_preview_start_ms = None
    self._player.stop()
    self._player.setSource(QUrl())
    super().done(result)

  def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
    if self._pending_preview_start_ms is None:
      return
    if status not in {
      QMediaPlayer.MediaStatus.LoadedMedia,
      QMediaPlayer.MediaStatus.BufferedMedia,
    }:
      return
    self._player.setPosition(self._pending_preview_start_ms)

  def _loop_selection_if_needed(self, position_ms: int) -> None:
    if not self._video_visible:
      return
    start_seconds, end_seconds = self._range_slider.values()
    start_ms = int(start_seconds * 1000)
    end_ms = int(end_seconds * 1000)
    if end_ms <= start_ms:
      return
    if position_ms >= end_ms:
      self._player.setPosition(start_ms)


class ClipWorkflow(QObject):
  """Owns clip dialog flow, preview refresh, and clip job completion."""

  def __init__(
    self,
    clip_service: ClipService,
    clip_cfg: ClipConfig,
    enqueue_job: Callable[[FfmpegJob], Path],
    show_message: Callable[[str, str | None, bool], None],
    clear_message: Callable[[], None],
    is_player_muted: Callable[[], bool],
    set_player_muted: Callable[[bool], None],
    parent: QObject | None = None,
  ) -> None:
    super().__init__(parent)
    self._clip_service = clip_service
    self._clip_cfg = clip_cfg
    self._enqueue_job = enqueue_job
    self._show_message = show_message
    self._clear_message = clear_message
    self._is_player_muted = is_player_muted
    self._set_player_muted = set_player_muted

  def run_clip_dialog(self, runtime: object, parent_widget: QWidget, rotation: int = 0) -> None:
    stage: ClipBufferStage | None = None
    dialog: ClipRangeDialog | None = None
    preview_timer: QTimer | None = None
    restore_mute_on_exit = False

    try:
      self._show_message("Clip", "Preparing clip...", True)
      stage = self._run_task(
        parent_widget,
        lambda: self._clip_service.prepare_stage(runtime, rotation),
      )
      total_seconds = max(ClipRangeDialog.MIN_DURATION, int(stage.total_seconds + 0.999))
      end_seconds = total_seconds
      start_seconds = max(0, end_seconds - int(self._clip_cfg.default_duration))

      stream_author = str(getattr(runtime, "stream_author", "stream"))
      stream_category = str(getattr(runtime, "stream_category", "unknown"))
      dialog = ClipRangeDialog(stream_author, stream_category, parent_widget)
      dialog.set_timeline_max(total_seconds)
      dialog.set_selected_range(start_seconds, end_seconds)
      dialog.set_video_source(stage.preview_path)

      preview_timer = QTimer(dialog)
      preview_timer.setSingleShot(True)
      preview_timer.setInterval(120)
      refresh_state = {"running": False, "dirty": False}

      def run_preview_refresh() -> None:
        # Guard against re-entrancy: refresh_clip_previews blocks on a nested
        # event loop, during which more range changes can arrive. Coalesce them
        # and always finish on the latest selected range.
        if refresh_state["running"]:
          refresh_state["dirty"] = True
          return
        refresh_state["running"] = True
        try:
          while True:
            refresh_state["dirty"] = False
            self.refresh_clip_previews(dialog, stage)
            if not refresh_state["dirty"]:
              break
        finally:
          refresh_state["running"] = False

      def on_range_changed() -> None:
        # Throttle rather than debounce: the slider is quantized to whole
        # seconds, so this fires at most once per second crossed. Update during
        # the drag instead of only after the handle is released.
        if refresh_state["running"]:
          refresh_state["dirty"] = True
        elif not preview_timer.isActive():
          preview_timer.start()

      preview_timer.timeout.connect(run_preview_refresh)
      dialog.on_range_changed(on_range_changed)

      self.refresh_clip_previews(dialog, stage)
      if not self._is_player_muted():
        self._set_player_muted(True)
        restore_mute_on_exit = True

      dialog_result = dialog.exec()

      if restore_mute_on_exit:
        self._set_player_muted(False)
        restore_mute_on_exit = False

      if dialog_result != dialog.DialogCode.Accepted:
        self._clip_service.cleanup(stage)
        self._clear_message()
        return

      start_selected, end_selected = dialog.selected_range()
      stream_author = str(getattr(runtime, "stream_author", "stream"))
      stream_category = str(getattr(runtime, "stream_category", "unknown"))
      stream_title = str(getattr(runtime, "stream_title", "untitled"))
      job = self._clip_service.build_export_job(
        stage,
        stream_author,
        stream_category,
        stream_title,
        float(start_selected),
        float(end_selected),
      )
      target_path = self._enqueue_job(job)
      log.info("clip: queued output=%s", target_path)
      self._show_message("Clip", f"Exporting: {target_path.name}", True)
    except Exception as exc:
      if stage is not None:
        self._clip_service.cleanup(stage)
      log.error("clip: failed: %s", exc)
      self._show_message("Clip failed", str(exc), False)
    finally:
      if restore_mute_on_exit:
        self._set_player_muted(False)

  def refresh_clip_previews(self, dialog: ClipRangeDialog, stage: ClipBufferStage) -> None:
    start_seconds, end_seconds = dialog.selected_range()
    start_image, end_image = self._run_task(
      dialog,
      lambda: self._clip_service.preview_frames(stage, float(start_seconds), float(end_seconds)),
    )
    dialog.set_preview_images(start_image, end_image)

  @staticmethod
  def _run_task(parent_widget: QWidget, task: Callable[[], object]) -> object:
    thread = QThread(parent_widget)
    worker = _TaskWorker(task)
    worker.moveToThread(thread)

    loop = QEventLoop()
    result_holder: dict[str, object] = {}

    def on_finished(value: object) -> None:
      result_holder["result"] = value
      loop.quit()

    def on_failed(exc: object) -> None:
      result_holder["error"] = exc
      loop.quit()

    thread.started.connect(worker.run)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)

    thread.start()
    loop.exec()
    thread.wait(3000)

    worker.deleteLater()
    thread.deleteLater()

    error = result_holder.get("error")
    if error is not None:
      if isinstance(error, Exception):
        raise error
      raise RuntimeError(str(error))

    return result_holder["result"]

  def handle_clip_job_finished(self, result: FfmpegJobResult) -> None:
    context = result.job.context
    if isinstance(context, ClipExportContext):
      self._clip_service.cleanup(context.stage)

    if result.success:
      log.info("clip: exported output=%s", result.job.target_path)
      self._show_message("Clip saved", result.job.target_path.name, False)
      return

    if result.job.stderr_path is not None:
      log.warning("clip: export failed code=%s stderr_log=%s", result.exit_code, result.job.stderr_path)
    else:
      log.warning("clip: export failed code=%s", result.exit_code)
    self._show_message("Clip failed", "Export failed", False)
