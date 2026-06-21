"""Main PyQt application shell and composition root."""

from collections.abc import Callable
import sys

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QKeyEvent, QResizeEvent
from PyQt6.QtWidgets import QApplication, QMainWindow

from .control_strip import ControlStrip
from .video_surface import VideoSurface

ShutdownLogger = Callable[[str], None]


class MainWindow(QMainWindow):
    def __init__(
        self,
        media_source: str,
        mpv_options: dict[str, object],
        trigger_radius: int,
        resize_debounce_ms: int,
        shutdown_logger: ShutdownLogger | None = None,
    ) -> None:
        super().__init__()
        self._shutting_down = False
        self._shutdown_logger = shutdown_logger
        self.setWindowTitle("Clippiti Player")
        self.resize(1280, 760)

        self.video = VideoSurface(media_source, mpv_options, shutdown_logger=self._shutdown_logger)
        self.setCentralWidget(self.video)

        self.strip = ControlStrip(self.video, self.video, trigger_radius)
        self.strip.raise_()

        self._reposition_timer = QTimer(self)
        self._reposition_timer.setSingleShot(True)
        self._reposition_timer.setInterval(max(0, int(resize_debounce_ms)))
        self._reposition_timer.timeout.connect(self.strip.reposition)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video.setFocus()

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        if self._shutdown_logger is not None:
            self._shutdown_logger("window: shutdown begin")
        self._reposition_timer.stop()
        self.strip.shutdown()
        self.video.shutdown()
        if self._shutdown_logger is not None:
            self._shutdown_logger("window: shutdown complete")

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown()
        super().closeEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reposition_timer.start()

    def handle_volume_wheel(self, delta_y: int) -> bool:
        if delta_y > 0:
            return self.strip.adjust_volume(5)
        if delta_y < 0:
            return self.strip.adjust_volume(-5)
        return False

    def handle_volume_key(self, key: int) -> bool:
        return self.strip.handle_volume_key(key)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self.handle_volume_key(event.key()):
            event.accept()
            return
        super().keyPressEvent(event)


def run_app(
    media_source: str,
    mpv_options: dict[str, object],
    trigger_radius: int,
    resize_debounce_ms: int,
    shutdown_logger: ShutdownLogger | None = None,
) -> int:
    app = QApplication(sys.argv)
    window = MainWindow(
        media_source,
        mpv_options,
        trigger_radius,
        resize_debounce_ms,
        shutdown_logger=shutdown_logger,
    )
    if shutdown_logger is not None:
        shutdown_logger("app: connected aboutToQuit")
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    if shutdown_logger is not None:
        shutdown_logger("app: event loop enter")
    return app.exec()
