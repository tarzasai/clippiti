"""Centered on-screen display overlay for transient player feedback."""

import logging

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget, QSizePolicy

log = logging.getLogger("clippiti.ui.osd")


class OsdOverlay(QFrame):
    TITLE_FONT_SIZE = 24
    DETAIL_FONT_SIZE = 22
    MAX_PARENT_WIDTH_RATIO = 0.60
    MAX_PARENT_HEIGHT_RATIO = 0.80
    PANEL_PADDING = 20

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._persistent = False
        self._panel_width_override: int | None = None

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(self.PANEL_PADDING, self.PANEL_PADDING, self.PANEL_PADDING, self.PANEL_PADDING)
        layout.setSpacing(6)
        layout.addWidget(self._title)
        layout.addWidget(self._detail)

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
            """
        )

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        parent.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.parentWidget() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            if self.isVisible():
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
        self._title.setText(title)

        if detail:
            self._detail.setText(detail)
            self._detail.show()
        else:
            self._detail.clear()
            self._detail.hide()

        self._apply_measured_panel_size()
        self._reposition()
        self.raise_()
        self.show()

        if persistent:
            self._hide_timer.stop()
        else:
            self._hide_timer.start(max(0, int(timeout_ms)))

    def clear_message(self) -> None:
        self._persistent = False
        self._hide_timer.stop()
        self.hide()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
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
