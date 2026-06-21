"""Main PyQt application shell and composition root."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
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
        self._volume = 70
        self._muted = False
        self.setWindowTitle("Clippiti Player")
        self.resize(1280, 760)

        self.video = VideoSurface(media_source, mpv_options, shutdown_logger=self._shutdown_logger)
        self.setCentralWidget(self.video)

        self.strip = ControlStrip(self.video, trigger_radius)
        self.strip.raise_()
        self._wire_toolbar_actions()
        self._apply_audio_state()

        self._reposition_timer = QTimer(self)
        self._reposition_timer.setSingleShot(True)
        self._reposition_timer.setInterval(max(0, int(resize_debounce_ms)))
        self._reposition_timer.timeout.connect(self.strip.reposition)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video.setFocus()

    def _wire_toolbar_actions(self) -> None:
        if self.strip.mute_action is not None:
            self.strip.mute_action.triggered.connect(self._mute_action)
        if self.strip.snapshot_action is not None:
            self.strip.snapshot_action.triggered.connect(self._snapshot_action)
        if self.strip.move_action is not None:
            self.strip.move_action.triggered.connect(self._move_toolbar_action)

    def _mute_action(self) -> None:
        self._muted = not self._muted
        self._apply_audio_state()

    def _snapshot_action(self) -> None:
        if self.video.render_ctx is None:
            return
        out = Path.home() / "Pictures" / "Clippiti" / "snapshots"
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = out / f"snapshot_{ts}.png"

        image = self.video.grabFramebuffer()
        if not image.isNull():
            image.save(str(target), "PNG")

    def _move_toolbar_action(self) -> None:
        mods = QApplication.keyboardModifiers()
        step = -1 if mods & Qt.KeyboardModifier.ControlModifier else 1
        self.strip.move_position(step)

    def _apply_audio_state(self) -> None:
        if self.video.player is not None:
            self.video.player.volume = self._volume
            self.video.player.mute = self._muted
        self.strip.set_audio_ui_state(self._volume, self._muted)

    def _adjust_volume(self, delta: int) -> bool:
        new_volume = max(0, min(100, self._volume + delta))
        if new_volume == self._volume:
            return False
        self._volume = new_volume
        if self._volume > 0 and self._muted:
            self._muted = False
        self._apply_audio_state()
        return True

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
