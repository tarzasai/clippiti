"""Centered on-screen display overlay for transient player feedback."""

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class OsdOverlay(QFrame):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._persistent = False

        self.setObjectName("osd-overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

        self._title = QLabel(self)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._detail = QLabel(self)
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
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
            QFrame#osd-overlay QLabel:first-child {
                font-size: 24px;
                font-weight: 700;
            }
            """
        )

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        parent.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.parentWidget() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
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

        self.adjustSize()
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
