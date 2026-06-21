#!/usr/bin/env python3
"""PyQt6 + python-mpv UI mockup for floating player controls with QToolBar.

Run:
    python doc/mockup/floating_controls_mockup.py
"""

from pathlib import Path
from datetime import datetime
import locale
import os
import sys

# libmpv requires C numeric locale (decimal dot) and can crash otherwise.
os.environ["LC_NUMERIC"] = "C"
locale.setlocale(locale.LC_NUMERIC, "C")

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeyEvent, QOpenGLContext, QResizeEvent
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMainWindow, QToolBar, QWidget

import mpv

# VIDEO_PATH = Path("/home/giorgio/Downloads/prototype_demo.mp4")
VIDEO_PATH = Path("/home/giorgio/Videos/Movies/Alien (1979) [director's cut]/Alien.1979.DC.2160p.4K.BluRay.x265.10bit.AAC5.1-[YTS.MX].mkv")
MOCKUP_START_SECONDS = 600  # Mockup-only convenience: start at 10:00.


class VideoSurface(QOpenGLWidget):
    frame_ready = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("video-surface")
        self.player: mpv.MPV | None = None
        self.render_ctx: mpv.MpvRenderContext | None = None
        self._gl_proc_addr: mpv.MpvGlGetProcAddressFn | None = None
        self.frame_ready.connect(self._maybe_paint_next_frame)

    def _get_proc_addr(self, _ctx, name) -> int:
        try:
            context = QOpenGLContext.currentContext()
            if context is None:
                return 0
            addr = context.getProcAddress(name)
            return int(addr) if addr is not None else 0
        except Exception:
            return 0

    def initializeGL(self) -> None:  # noqa: N802
        if self.player is not None:
            return

        # Qt may re-apply system locale; enforce C numeric locale before mpv init.
        locale.setlocale(locale.LC_NUMERIC, "C")

        # Use libmpv render API with this widget's OpenGL context.
        self.player = mpv.MPV(
            vo="libmpv",
            osc=False,
            idle="yes",
            input_default_bindings=False,
            input_vo_keyboard=False,
            loop_file="inf",
            keep_open="yes",
            volume=70,
            start=MOCKUP_START_SECONDS,
            terminal=False,
        )

        self._gl_proc_addr = mpv.MpvGlGetProcAddressFn(self._get_proc_addr)
        self.render_ctx = mpv.MpvRenderContext(
            self.player,
            "opengl",
            opengl_init_params={"get_proc_address": self._gl_proc_addr},
            advanced_control=True,
        )
        self.render_ctx.update_cb = self.frame_ready.emit
        self.player.play(str(VIDEO_PATH))

    def _maybe_paint_next_frame(self) -> None:
        if self.render_ctx is None:
            return
        if self.render_ctx.update():
            self.update()

    def paintGL(self) -> None:  # noqa: N802
        if self.render_ctx is None:
            return

        dpr = self.devicePixelRatioF()
        width = max(1, int(self.width() * dpr))
        height = max(1, int(self.height() * dpr))
        self.render_ctx.render(
            opengl_fbo={
                "fbo": int(self.defaultFramebufferObject()),
                "w": width,
                "h": height,
                "internal_format": 0,
            },
            flip_y=True,
        )

    def wheelEvent(self, event) -> None:  # noqa: N802
        window = self.window()
        handler = getattr(window, "handle_volume_wheel", None)
        if callable(handler) and handler(event.angleDelta().y()):
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        window = self.window()
        handler = getattr(window, "handle_volume_key", None)
        if callable(handler) and handler(event.key()):
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if self.render_ctx is not None:
                self.render_ctx.free()
            if self.player is not None:
                self.player.terminate()
        finally:
            self.render_ctx = None
            self.player = None
            self._gl_proc_addr = None
        super().closeEvent(event)


class ControlStrip(QFrame):
    """Floating icon strip with QToolBar that slides in/out from window edge on hover.

    Six icon actions are managed by QToolBar. In collapsed state only the
    mute/volume-indicator button is visible, with others clipped off-screen.
    Hovering shows the full strip.

    The move button cycles through 8 anchor positions: 4 corners × 2 edge orientations.
    """

    BTN_SIZE = 56
    ICON_SIZE = 28
    MARGIN = 12
    ANIM_MS = 180
    HIDDEN = 5
    TOTAL = 6
    VISIBLE = TOTAL - HIDDEN
    TRIGGER_PAD = 12
    TRIGGER_RADIUS = 400
    COLLAPSE_DELAY_MS = 150

    STATES: list[tuple[str, str]] = [
        ("right",  "top"),
        ("top",    "right"),
        ("right",  "bottom"),
        ("bottom", "right"),
        ("bottom", "left"),
        ("left",   "bottom"),
        ("left",   "top"),
        ("top",    "left"),
    ]

    def __init__(self, parent: QWidget, video: "VideoSurface") -> None:
        super().__init__(parent)
        self._video = video
        self._state_idx = 0
        self._hovering = False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        self.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet("padding: 0px;")

        self._anim = QPropertyAnimation(self, b"pos")
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(self.COLLAPSE_DELAY_MS)
        self._collapse_timer.timeout.connect(lambda: self._set_hovering(False))

        parent.installEventFilter(self)
        parent.setMouseTracking(True)
        self.setMouseTracking(True)

        # Create toolbar inside this frame
        self._toolbar = QToolBar(self)
        self._toolbar.setIconSize(QSize(self.ICON_SIZE, self.ICON_SIZE))
        self._toolbar.setMovable(False)
        self._toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar_layout = self._toolbar.layout()
        if toolbar_layout is not None:
            toolbar_layout.setContentsMargins(0, 0, 0, 0)
            toolbar_layout.setSpacing(0)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toolbar)

        specs = [
            ("audio-volume-muted-blocking-symbolic", "Mute / Unmute", self._do_mute),
            ("screenshot-app-symbolic", "Snapshot", self._do_snapshot),
            ("edit-cut-symbolic", "Clip", None),
            ("media-record-symbolic", "Record", None),
            ("object-move-symbolic", "Move panel (Ctrl+Click: reverse)", self._do_move),
            ("settings-app-symbolic", "Settings", None),
        ]

        self._mute_action = None
        self._actions = []
        self._volume = 70
        self._muted = False

        for idx, (icon_name, tip, slot) in enumerate(specs):
            action = self._toolbar.addAction(QIcon.fromTheme(icon_name), tip)
            self._actions.append(action)
            if idx == 0:
                self._mute_action = action
            if slot:
                action.triggered.connect(slot)

        # Resize button widgets in toolbar
        for action in self._toolbar.actions():
            widget = self._toolbar.widgetForAction(action)
            if widget:
                widget.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
                set_auto_raise = getattr(widget, "setAutoRaise", None)
                if callable(set_auto_raise):
                    set_auto_raise(False)

        self._place_buttons()
        self._update_mute_icon()

    def _place_buttons(self) -> None:
        edge = self.STATES[self._state_idx][0]
        B = self.BTN_SIZE
        is_horiz = edge in ("left", "right")
        reverse = edge in ("left", "top")

        desired = [self._actions[i] for i in (reversed(range(self.TOTAL)) if reverse else range(self.TOTAL))]
        current = self._toolbar.actions()
        if current != desired:
            for action in current:
                self._toolbar.removeAction(action)
            for action in desired:
                self._toolbar.addAction(action)

        self._toolbar.setOrientation(Qt.Orientation.Horizontal if is_horiz else Qt.Orientation.Vertical)
        self._toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar_layout = self._toolbar.layout()
        if toolbar_layout is not None:
            toolbar_layout.setContentsMargins(0, 0, 0, 0)
            toolbar_layout.setSpacing(0)

        for action in self._toolbar.actions():
            widget = self._toolbar.widgetForAction(action)
            if widget:
                widget.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
                widget.setContentsMargins(0, 0, 0, 0)
                set_auto_raise = getattr(widget, "setAutoRaise", None)
                if callable(set_auto_raise):
                    set_auto_raise(False)

        self._toolbar.adjustSize()
        hint = self._toolbar.sizeHint()

        base_w = self.TOTAL * B if is_horiz else B
        base_h = B if is_horiz else self.TOTAL * B
        self.setFixedSize(max(base_w, hint.width()), max(base_h, hint.height()))

    def _collapsed_pos(self) -> QPoint:
        p = self.parentWidget()
        if p is None:
            return QPoint(0, 0)
        pw, ph = p.width(), p.height()
        edge, side = self.STATES[self._state_idx]
        M, B, V = self.MARGIN, self.BTN_SIZE, self.VISIBLE
        H = self.HIDDEN

        if edge == "right":
            return QPoint(pw - V * B, M if side == "top" else ph - B - M)
        if edge == "left":
            return QPoint(-H * B, M if side == "top" else ph - B - M)
        if edge == "top":
            return QPoint(pw - B - M if side == "right" else M, -H * B)
        return QPoint(pw - B - M if side == "right" else M, ph - V * B)

    def _expanded_pos(self) -> QPoint:
        p = self.parentWidget()
        if p is None:
            return QPoint(0, 0)
        pw, ph = p.width(), p.height()
        edge, side = self.STATES[self._state_idx]
        M, B, T = self.MARGIN, self.BTN_SIZE, self.TOTAL

        if edge == "right":
            return QPoint(pw - T * B, M if side == "top" else ph - B - M)
        if edge == "left":
            return QPoint(0, M if side == "top" else ph - B - M)
        if edge == "top":
            return QPoint(pw - B - M if side == "right" else M, 0)
        return QPoint(pw - B - M if side == "right" else M, ph - T * B)

    def _animate_to(self, target: QPoint) -> None:
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(target)
        self._anim.start()

    def _set_hovering(self, hovering: bool) -> None:
        if hovering:
            self._collapse_timer.stop()
        if hovering == self._hovering:
            return
        self._hovering = hovering
        self._animate_to(self._expanded_pos() if hovering else self._collapsed_pos())

    def _schedule_collapse(self) -> None:
        if self._hovering and not self._collapse_timer.isActive():
            self._collapse_timer.start()

    def _expanded_visible_rect_in_parent(self) -> QRect:
        parent = self.parentWidget()
        if parent is None:
            return QRect()
        rect = QRect(self._expanded_pos(), self.size()).intersected(parent.rect())
        return rect.adjusted(-self.TRIGGER_PAD, -self.TRIGGER_PAD, self.TRIGGER_PAD, self.TRIGGER_PAD)

    def _in_corner_trigger(self, pos: QPoint) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return False

        pw, ph = parent.width(), parent.height()
        r = self.TRIGGER_RADIUS
        corner_group = self._state_idx // 2

        if corner_group == 0:
            cx, cy = pw - 1, 0
            dx, dy = cx - pos.x(), pos.y() - cy
        elif corner_group == 1:
            cx, cy = pw - 1, ph - 1
            dx, dy = cx - pos.x(), cy - pos.y()
        elif corner_group == 2:
            cx, cy = 0, ph - 1
            dx, dy = pos.x() - cx, cy - pos.y()
        else:
            cx, cy = 0, 0
            dx, dy = pos.x() - cx, pos.y() - cy

        if dx < 0 or dy < 0:
            return False
        if dx > r or dy > r:
            return False
        return (dx * dx + dy * dy) <= (r * r)

    def reposition(self) -> None:
        self._place_buttons()
        self.move(self._expanded_pos() if self._hovering else self._collapsed_pos())

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.parentWidget():
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self.reposition()
            elif event.type() == QEvent.Type.MouseMove:
                mouse_pos = event.position().toPoint()
                in_trigger = self._in_corner_trigger(mouse_pos)
                in_strip = self._expanded_visible_rect_in_parent().contains(mouse_pos)
                if in_trigger or in_strip:
                    self._set_hovering(True)
                else:
                    self._schedule_collapse()
        return super().eventFilter(obj, event)

    def _update_mute_icon(self) -> None:
        if self._mute_action is None:
            return

        if self._muted:
            icon_name = "audio-volume-muted-symbolic"
            label = "MUTE"
        elif self._volume <= 0:
            icon_name = "audio-volume-muted-symbolic"
            label = "MUTE"
        elif self._volume < 34:
            icon_name = "audio-volume-low-symbolic"
            label = "LOW"
        elif self._volume < 67:
            icon_name = "audio-volume-medium-symbolic"
            label = "MED"
        else:
            icon_name = "audio-volume-high-symbolic"
            label = "HIGH"

        icon = QIcon.fromTheme(icon_name)
        self._mute_action.setIcon(icon)
        self._mute_action.setText(label)

    def _do_mute(self) -> None:
        if self._video.player is None:
            return
        self._muted = not self._muted
        self._video.player.mute = self._muted
        self._update_mute_icon()

    def _apply_volume(self, volume: int) -> bool:
        new_volume = max(0, min(100, volume))
        if new_volume == self._volume:
            return False
        self._volume = new_volume
        if self._video.player is not None:
            self._video.player.volume = self._volume
        if self._volume > 0 and self._muted:
            self._muted = False
            if self._video.player is not None:
                self._video.player.mute = False
        self._update_mute_icon()
        return True

    def adjust_volume(self, delta: int) -> bool:
        return self._apply_volume(self._volume + delta)

    def handle_volume_key(self, key: int) -> bool:
        if key in (Qt.Key.Key_Minus, Qt.Key.Key_PageDown):
            return self.adjust_volume(-5)
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_PageUp):
            return self.adjust_volume(5)
        return False

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.angleDelta().y() > 0 and self.adjust_volume(5):
            event.accept()
            return
        if event.angleDelta().y() < 0 and self.adjust_volume(-5):
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self.handle_volume_key(event.key()):
            event.accept()
            return
        super().keyPressEvent(event)

    def _do_move(self) -> None:
        self._anim.stop()
        mods = QApplication.keyboardModifiers()
        step = -1 if mods & Qt.KeyboardModifier.ControlModifier else 1
        self._state_idx = (self._state_idx + step) % len(self.STATES)
        self._hovering = False
        self._place_buttons()
        self.move(self._collapsed_pos())
        self.raise_()

    def _do_snapshot(self) -> None:
        if self._video.render_ctx is None:
            return
        out = Path.home() / "Pictures" / "Clippiti" / "snapshots"
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = out / f"mockup_snapshot_{ts}.png"

        image = self._video.grabFramebuffer()
        if not image.isNull():
            image.save(str(target), "PNG")


class MockupWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Clippiti Floating Controls Mockup")
        self.resize(1280, 760)

        if not VIDEO_PATH.exists():
            raise FileNotFoundError(f"Video not found: {VIDEO_PATH}")

        self.video = VideoSurface()
        self.setCentralWidget(self.video)

        self.strip = ControlStrip(self.video, self.video)
        self.strip.raise_()

        self._reposition_timer = QTimer(self)
        self._reposition_timer.setSingleShot(True)
        self._reposition_timer.setInterval(40)
        self._reposition_timer.timeout.connect(self.strip.reposition)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video.setFocus()

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


def main() -> int:
    app = QApplication(sys.argv)
    window = MockupWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
