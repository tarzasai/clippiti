"""Main PyQt application shell and composition root."""

from collections.abc import Callable
from dataclasses import dataclass
import sys
import logging

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QKeyEvent, QResizeEvent
from PyQt6.QtWidgets import QApplication, QMainWindow

from .control_strip import ControlStrip
from .osd import OsdOverlay
from .video_surface import VideoSurface

log = logging.getLogger("clippiti")


@dataclass
class AppRunResult:
    exit_code: int
    startup_result: object | None = None


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
    "<code><b>H</b></code> - Help<br>"
    "<code><b>S</b></code> - Snapshot<br>"
    "<code><b>C</b></code> - Clip dialog<br>"
    "<code><b>R</b></code> - Start / stop recording<br>"
    "<code><b>M</b></code> - Mute / Unmute<br>"
    "<code><b>P</b></code> - Pin / Unpin toolbar<br>"
    "<code><b>T</b></code> - Next toolbar position (<code><b>Shift+T</b></code> Previous)<br>"
    "<code><b>-/+</b></code> &nbsp; <code><b>PgDn/PgUp</b></code> &nbsp; <code><b>Wheel</b></code> - Volume"
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        media_source: str | None,
        mpv_options: dict[str, object],
        trigger_radius: int,
        resize_debounce_ms: int,
    ) -> None:
        super().__init__()
        self._shutting_down = False
        self.setWindowTitle("Clippiti Player")
        self.resize(1280, 760)

        self.video = VideoSurface(media_source, mpv_options)
        self.setCentralWidget(self.video)

        self.osd = OsdOverlay(self.video)
        if not media_source:
            self.osd.show_message("loading stream", persistent=True)

        self.strip = ControlStrip(
            self.video,
            self.video,
            trigger_radius,
            on_osd_message=self.show_osd_message,
        )
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
        log.debug("window: shutdown begin")
        self._reposition_timer.stop()
        self.strip.shutdown()
        self.video.shutdown()
        log.info("window: shutdown complete")

    def set_window_title(self, title: str) -> None:
        self.setWindowTitle(title)

    def set_media_source(self, media_source: str) -> None:
        self.video.set_media_source(media_source)
        self.strip.sync_player_state()
        self.osd.clear_message()

    def show_osd_message(self, title: str, detail: str | None = None, persistent: bool = False) -> None:
        self.osd.show_message(title, detail, persistent=persistent)

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
        key = event.key()
        mods = event.modifiers()

        if key == Qt.Key.Key_H:
            if self.osd.isVisible():
                self.osd.clear_message()
            else:
                self.osd.show_message("keyboard shortcuts", _HELP_TEXT, persistent=True)
            event.accept()
            return

        if key == Qt.Key.Key_S:
            self.strip.trigger_snapshot()
            self.osd.show_message("snapshot saved")
            event.accept()
            return

        if key == Qt.Key.Key_C:
            self.osd.show_message("clip", "Clip dialog coming soon")
            event.accept()
            return

        if key == Qt.Key.Key_R:
            self.osd.show_message("record", "Recording coming soon")
            event.accept()
            return

        if key == Qt.Key.Key_M:
            self.strip.trigger_mute()
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
    startup_task: Callable[[], object] | None = None,
    on_startup_ready: Callable[[MainWindow, object], None] | None = None,
    on_startup_failed: Callable[[Exception], None] | None = None,
    on_startup_cancel: Callable[[], None] | None = None,
) -> AppRunResult:
    app = QApplication(sys.argv)
    window = MainWindow(
        media_source,
        mpv_options,
        trigger_radius,
        resize_debounce_ms,
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
