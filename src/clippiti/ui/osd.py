"""Centered on-screen display overlay for transient player feedback."""

import logging
from pathlib import Path

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QSizePolicy

log = logging.getLogger("clippiti")


class OsdOverlay(QFrame):
  TITLE_FONT_SIZE = 24
  DETAIL_FONT_SIZE = 22
  SNAPSHOT_PATH_FONT_SIZE = 20
  MAX_PARENT_WIDTH_RATIO = 0.60
  MAX_PARENT_HEIGHT_RATIO = 0.80
  SNAPSHOT_BAND_HEIGHT_RATIO = 0.25
  SNAPSHOT_BAND_WIDTH_RATIO = 1.00
  SNAPSHOT_MIN_HEIGHT = 110
  PANEL_PADDING = 20
  MESSAGE_LAYOUT_SPACING = 6
  SNAPSHOT_LAYOUT_SPACING = 0
  SNAPSHOT_CONTENT_GAP = 14

  def __init__(self, parent: QWidget) -> None:
    super().__init__(parent)
    self._persistent = False
    self._panel_width_override: int | None = None
    self._mode = "message"

    self.setObjectName("osd-overlay")
    self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    self.hide()

    self._title = QLabel(self)
    self._title.setObjectName("osd-title")
    self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self._title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    title_font = self._title.font()
    title_font.setPixelSize(self.TITLE_FONT_SIZE)
    title_font.setBold(True)
    self._title.setFont(title_font)

    self._detail = QLabel(self)
    self._detail.setObjectName("osd-detail")
    self._detail.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    self._detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    self._detail.setTextFormat(Qt.TextFormat.RichText)
    detail_font = self._detail.font()
    detail_font.setPixelSize(self.DETAIL_FONT_SIZE)
    detail_font.setWeight(500)
    self._detail.setFont(detail_font)
    self._detail.hide()

    self._snapshot_row = QWidget(self)
    self._snapshot_row.setObjectName("osd-snapshot-row")
    self._snapshot_row.hide()

    self._snapshot_thumb = QLabel(self._snapshot_row)
    self._snapshot_thumb.setObjectName("osd-snapshot-thumb")
    self._snapshot_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self._snapshot_thumb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    self._snapshot_path = QLabel(self._snapshot_row)
    self._snapshot_path.setObjectName("osd-snapshot-path")
    self._snapshot_path.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    self._snapshot_path.setWordWrap(True)
    self._snapshot_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    snapshot_font = self._snapshot_path.font()
    snapshot_font.setPixelSize(self.SNAPSHOT_PATH_FONT_SIZE)
    snapshot_font.setWeight(500)
    self._snapshot_path.setFont(snapshot_font)

    self._snapshot_layout = QHBoxLayout(self._snapshot_row)
    self._snapshot_layout.setContentsMargins(0, 0, 0, 0)
    self._snapshot_layout.setSpacing(self.SNAPSHOT_CONTENT_GAP)
    self._snapshot_layout.addWidget(self._snapshot_thumb)
    self._snapshot_layout.addWidget(self._snapshot_path, 1)

    self._layout = QVBoxLayout(self)
    self._layout.setContentsMargins(
      self.PANEL_PADDING,
      self.PANEL_PADDING,
      self.PANEL_PADDING,
      self.PANEL_PADDING,
    )
    self._layout.setSpacing(self.MESSAGE_LAYOUT_SPACING)
    self._layout.addWidget(self._title)
    self._layout.addWidget(self._detail)
    self._layout.addWidget(self._snapshot_row)

    self.setStyleSheet(
      """
      QFrame#osd-overlay {
        background-color: rgba(12, 12, 16, 185);
        border: 1px solid rgba(255, 255, 255, 38);
        border-radius: 18px;
      }
      QFrame#osd-overlay QLabel {
        color: rgb(245, 247, 250);
      }
      QLabel#osd-snapshot-thumb {
        background-color: rgba(255, 255, 255, 20);
        border: 1px solid rgba(255, 255, 255, 50);
        border-radius: 8px;
      }
      """
    )

    self._hide_timer = QTimer(self)
    self._hide_timer.setSingleShot(True)
    self._hide_timer.timeout.connect(self.hide)

    parent.installEventFilter(self)

  def eventFilter(self, obj, event) -> bool:  # noqa: N802
    if obj is self.parentWidget() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
      if self.isVisible():
        if self._mode == "snapshot":
          self._apply_snapshot_panel_size()
        else:
          self._apply_measured_panel_size()
      self._reposition()
    return super().eventFilter(obj, event)

  def show_message(
    self,
    title: str,
    detail: str | None = None,
    *,
    persistent: bool = False,
    timeout_ms: int = 1400,
  ) -> None:
    self._persistent = persistent
    self._mode = "message"
    self._layout.setContentsMargins(
      self.PANEL_PADDING,
      self.PANEL_PADDING,
      self.PANEL_PADDING,
      self.PANEL_PADDING,
    )
    self._layout.setSpacing(self.MESSAGE_LAYOUT_SPACING)
    self._snapshot_layout.setContentsMargins(0, 0, 0, 0)
    self._snapshot_layout.setSpacing(self.SNAPSHOT_CONTENT_GAP)
    self._title.show()
    if detail:
      self._detail.show()
    else:
      self._detail.hide()
    self._snapshot_row.hide()
    self._title.setText(title)

    if detail:
      self._detail.setText(detail)
    else:
      self._detail.clear()

    self._apply_measured_panel_size()
    self._reposition()
    self.raise_()
    self.show()

    if persistent:
      self._hide_timer.stop()
    else:
      self._hide_timer.start(max(0, int(timeout_ms)))

  def show_snapshot_preview(self, image_path: str, *, timeout_ms: int = 2000) -> None:
    self._persistent = False
    self._mode = "snapshot"
    self._layout.setContentsMargins(0, 0, 0, 0)
    self._layout.setSpacing(self.SNAPSHOT_LAYOUT_SPACING)
    self._snapshot_layout.setContentsMargins(0, 0, 0, 0)
    self._snapshot_layout.setSpacing(self.SNAPSHOT_CONTENT_GAP)
    self._title.hide()
    self._detail.hide()
    self._snapshot_row.show()
    self._snapshot_path.setText(f"Snapshot saved:\n{Path(image_path)}")

    self._apply_snapshot_panel_size()
    self._apply_snapshot_thumbnail(image_path)
    self._reposition()
    self.raise_()
    self.show()
    self._hide_timer.start(max(0, int(timeout_ms)))

  def clear_message(self) -> None:
    self._persistent = False
    self._mode = "message"
    self._hide_timer.stop()
    self.hide()

  def _reposition(self) -> None:
    parent = self.parentWidget()
    if parent is None:
      return
    if self._mode == "snapshot":
      x = 0
      y = 0
    else:
      x = max(0, (parent.width() - self.width()) // 2)
      y = max(0, (parent.height() - self.height()) // 2)
    self.move(x, y)

  def _readjust_all(self, word_wrap: bool = False) -> None:
    self._title.setWordWrap(word_wrap)
    self._detail.setWordWrap(word_wrap)
    self._title.adjustSize()
    self._detail.adjustSize()
    self.adjustSize()

  def _apply_measured_panel_size(self) -> None:
    parent = self.parentWidget()
    if parent is None:
      return

    max_width = max(220, int(parent.width() * self.MAX_PARENT_WIDTH_RATIO))
    max_height = max(120, int(parent.height() * self.MAX_PARENT_HEIGHT_RATIO))

    self.setMinimumSize(0, 0)
    self.setMaximumSize(5000, 5000)
    self._readjust_all(word_wrap=False)

    full_width = self.width()
    full_height = self.height()

    target_width = min(max_width, full_width)
    target_height = min(max_height, full_height)

    self.setMinimumSize(target_width, target_height)
    self.setMaximumSize(target_width, target_height)
    self._readjust_all(word_wrap=True)

    log.debug(
      f"OSD: max size={max_width}x{max_height}"
      f" full size={full_width}x{full_height}"
      f" target size={target_width}x{target_height}"
      f" assigned size={self.width()}x{self.height()}"
    )

  def _apply_snapshot_panel_size(self) -> None:
    parent = self.parentWidget()
    if parent is None:
      return

    target_width = max(280, int(parent.width() * self.SNAPSHOT_BAND_WIDTH_RATIO))
    target_height = max(self.SNAPSHOT_MIN_HEIGHT, int(parent.height() * self.SNAPSHOT_BAND_HEIGHT_RATIO))

    self.setMinimumSize(target_width, target_height)
    self.setMaximumSize(target_width, target_height)
    self.adjustSize()

  def _apply_snapshot_thumbnail(self, image_path: str) -> None:
    panel_height = max(self.height(), self.SNAPSHOT_MIN_HEIGHT)
    thumb_target = max(72, panel_height)
    max_thumb_width = max(72, int(self.width() * 0.28))

    pixmap = QPixmap(image_path)
    if pixmap.isNull():
      self._snapshot_thumb.setPixmap(QPixmap())
      self._snapshot_thumb.setText("n/a")
      self._snapshot_thumb.setFixedSize(thumb_target, thumb_target)
      return

    scaled = pixmap.scaled(
      max_thumb_width,
      thumb_target,
      Qt.AspectRatioMode.KeepAspectRatio,
      Qt.TransformationMode.SmoothTransformation,
    )
    self._snapshot_thumb.setText("")
    self._snapshot_thumb.setPixmap(scaled)
    self._snapshot_thumb.setFixedSize(scaled.size())
