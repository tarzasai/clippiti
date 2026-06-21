"""Floating control strip widget for player controls."""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Callable

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QSize, QTimer, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QToolBar, QWidget

if TYPE_CHECKING:
    from .video_surface import VideoSurface


class ControlStrip(QFrame):
    BTN_SIZE = 56
    ICON_SIZE = 28
    MARGIN = 12
    ANIM_MS = 180
    HIDDEN = 5
    TOTAL = 6
    VISIBLE = TOTAL - HIDDEN
    TRIGGER_PAD = 12
    COLLAPSE_DELAY_MS = 150

    STATES: list[tuple[str, str]] = [
        ("right", "top"),
        ("top", "right"),
        ("right", "bottom"),
        ("bottom", "right"),
        ("bottom", "left"),
        ("left", "bottom"),
        ("left", "top"),
        ("top", "left"),
    ]

    def __init__(
        self,
        parent: QWidget,
        video: "VideoSurface",
        trigger_radius: int,
        on_osd_message: Callable[[str, str | None, bool], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._video = video
        self._trigger_radius = max(50, trigger_radius)
        self._on_osd_message = on_osd_message
        self._state_idx = 0
        self._hovering = False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        self.setContentsMargins(0, 0, 0, 0)

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

        for action in self._toolbar.actions():
            widget = self._toolbar.widgetForAction(action)
            if widget:
                widget.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
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
        r = self._trigger_radius
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

        self._mute_action.setIcon(QIcon.fromTheme(icon_name))
        self._mute_action.setText(label)

    def _do_mute(self) -> None:
        self._muted = not self._muted
        if self._video.player is not None:
            self._video.player.mute = self._muted
        self._update_mute_icon()
        self.sync_player_state()
        self._show_volume_osd()

    def _apply_volume(self, volume: int) -> bool:
        new_volume = max(0, min(100, volume))
        if new_volume == self._volume:
            return False
        self._volume = new_volume
        if self._volume > 0 and self._muted:
            self._muted = False
        self.sync_player_state()
        self._update_mute_icon()
        self._show_volume_osd()
        return True

    def sync_player_state(self) -> None:
        if self._video.player is None:
            return
        self._video.player.volume = self._volume
        self._video.player.mute = self._muted

    def _show_volume_osd(self) -> None:
        if self._on_osd_message is None:
            return
        self._on_osd_message(self.volume_osd_title(), self.volume_osd_detail(), False)

    def volume_osd_title(self) -> str:
        if self._muted or self._volume <= 0:
            return "Muted"
        return f"Volume {self._volume}%"

    def volume_osd_detail(self) -> str | None:
        if self._muted or self._volume <= 0:
            return None
        blocks = max(1, min(10, round(self._volume / 10)))
        return "|" * blocks

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
        target = out / f"snapshot_{ts}.png"

        image = self._video.grabFramebuffer()
        if not image.isNull():
            image.save(str(target), "PNG")

    def shutdown(self) -> None:
        self._anim.stop()
        self._collapse_timer.stop()
