"""Clip range dialog with static frame previews and optional video preview."""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedLayout, QVBoxLayout, QWidget


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clip range")
        self._start_preview_image: Path | None = None
        self._end_preview_image: Path | None = None
        self._video_source_path: Path | None = None
        self._video_visible = False

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
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(video_path)))
        self._seek_to_start()
        if self._video_visible:
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
        self._player.setPosition(int(start * 1000))

    def _toggle_video_preview(self) -> None:
        self._video_visible = not self._video_visible
        if self._video_visible:
            self._content_stack.setCurrentWidget(self._video_widget)
            self._toggle_video_button.setText("Hide video preview")
            if self._video_source_path is not None and self._video_source_path.exists():
                self._seek_to_start()
                self._player.play()
        else:
            self._content_stack.setCurrentWidget(self._selection_widget)
            self._toggle_video_button.setText("Show video preview")
            self._player.pause()

    def done(self, result: int) -> None:
        self._player.stop()
        self._player.setSource(QUrl())
        super().done(result)

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
