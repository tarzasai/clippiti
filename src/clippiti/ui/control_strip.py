"""Floating control strip widget for player controls."""

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QSize, QTimer, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QToolBar, QWidget


class ControlStrip(QFrame):
    BTN_SIZE = 56
    ICON_SIZE = 28
    MARGIN = 12
    ANIM_MS = 180
    TOTAL = 6
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
        trigger_radius: int,
    ) -> None:
        super().__init__(parent)
        self._trigger_radius = max(50, trigger_radius)
        self._state_idx = 0
        self._hovering = False
        self._volume = 70
        self._muted = False
        self._pinned = False
        self._recording_active = False
        self._record_pulse_effect: QGraphicsOpacityEffect | None = None
        self._record_pulse_anim: QPropertyAnimation | None = None

        self._toolbar = QToolBar(self)
        self._toolbar.setIconSize(QSize(self.ICON_SIZE, self.ICON_SIZE))
        self._toolbar.setMovable(False)
        self._toolbar.setContentsMargins(0, 0, 0, 0)

        self.mute_action = self._toolbar.addAction(
            QIcon.fromTheme("audio-volume-muted-blocking-symbolic"),
            "Mute / Unmute"
        )
        self.record_action = self._toolbar.addAction(
            QIcon.fromTheme("media-record-symbolic"),
            "Record"
        )
        self.clip_action = self._toolbar.addAction(
            QIcon.fromTheme("edit-cut-symbolic"),
            "Clip"
        )
        self.snapshot_action = self._toolbar.addAction(
            QIcon.fromTheme("screenshot-app-symbolic"),
            "Snapshot"
        )
        self.move_action = self._toolbar.addAction(
            QIcon.fromTheme("object-move-symbolic"),
            "Move panel (Ctrl+Click: reverse)"
        )
        self.settings_action = self._toolbar.addAction(
            QIcon.fromTheme("settings-app-symbolic"),
            "Settings"
        )

        # This list is only used to control the order of buttons in the toolbar
        self._actions = [
            self.mute_action,
            self.record_action,
            self.clip_action,
            self.snapshot_action,
            self.move_action,
            self.settings_action,
        ]

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

        for action in self._toolbar.actions():
            widget = self._toolbar.widgetForAction(action)
            if widget:
                widget.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
                set_auto_raise = getattr(widget, "setAutoRaise", None)
                if callable(set_auto_raise):
                    set_auto_raise(False)

        toolbar_layout = self._toolbar.layout()
        if toolbar_layout is not None:
            toolbar_layout.setContentsMargins(0, 0, 0, 0)
            toolbar_layout.setSpacing(0)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toolbar)

        self._place_buttons()
        self._update_audio_icon()

        parent.installEventFilter(self)
        parent.setMouseTracking(True)
        self.setMouseTracking(True)

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
        M, B = self.MARGIN, self.BTN_SIZE
        V = self._collapsed_visible_buttons()
        H = self.TOTAL - V

        if edge == "right":
            return QPoint(pw - V * B, M if side == "top" else ph - B - M)
        if edge == "left":
            return QPoint(-H * B, M if side == "top" else ph - B - M)
        if edge == "top":
            return QPoint(pw - B - M if side == "right" else M, -H * B)
        return QPoint(pw - B - M if side == "right" else M, ph - V * B)

    def _collapsed_visible_buttons(self) -> int:
        if self._pinned:
            return self.TOTAL
        return 2 if self._recording_active else 1

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
        if self._pinned and not hovering:
            return
        if hovering:
            self._collapse_timer.stop()
        if hovering == self._hovering:
            return
        self._hovering = hovering
        self._animate_to(self._expanded_pos() if hovering else self._collapsed_pos())

    def _schedule_collapse(self) -> None:
        if self._pinned:
            return
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

    def _update_audio_icon(self) -> None:
        if self._muted:
            icon_name = "audio-volume-muted-blocking-symbolic"
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

        self.mute_action.setIcon(QIcon.fromTheme(icon_name))
        self.mute_action.setToolTip(label)

    def set_audio_ui_state(self, volume: int, muted: bool) -> None:
        self._volume = max(0, min(100, int(volume)))
        self._muted = bool(muted)
        self._update_audio_icon()

    def move_position(self, step: int = 1) -> None:
        self._anim.stop()
        self._state_idx = (self._state_idx + step) % len(self.STATES)
        target_hovering = self._pinned
        self._hovering = target_hovering
        self._place_buttons()
        self.move(self._expanded_pos() if target_hovering else self._collapsed_pos())
        self.raise_()

    def toggle_pin(self) -> bool:
        """Toggle pinned state. Returns new pinned state."""
        self._pinned = not self._pinned
        if self._pinned:
            self._collapse_timer.stop()
            if not self._hovering:
                self._hovering = True
                self._animate_to(self._expanded_pos())
        return self._pinned

    def set_recording(self, active: bool) -> None:
        self._recording_active = bool(active)
        action = self.record_action
        if action is None:
            return
        if active:
            action.setIcon(QIcon.fromTheme("media-playback-stop-symbolic"))
            action.setText("Stop Recording")
        else:
            action.setIcon(QIcon.fromTheme("media-record-symbolic"))
            action.setText("Record")

        self._set_record_pulse(active)

        if self._pinned:
            self.move(self._expanded_pos())
        elif self._hovering:
            self.move(self._expanded_pos())
        else:
            self._animate_to(self._collapsed_pos())

    def _record_button_widget(self) -> QWidget | None:
        if self.record_action is None:
            return None
        return self._toolbar.widgetForAction(self.record_action)

    def _set_record_pulse(self, active: bool) -> None:
        button = self._record_button_widget()
        if button is None:
            return

        if self._record_pulse_effect is None:
            self._record_pulse_effect = QGraphicsOpacityEffect(button)
            self._record_pulse_effect.setOpacity(1.0)
            button.setGraphicsEffect(self._record_pulse_effect)
        else:
            button.setGraphicsEffect(self._record_pulse_effect)

        if self._record_pulse_anim is None:
            self._record_pulse_anim = QPropertyAnimation(self._record_pulse_effect, b"opacity", self)
            self._record_pulse_anim.setDuration(2000)
            self._record_pulse_anim.setLoopCount(-1)
            self._record_pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
            self._record_pulse_anim.setKeyValueAt(0.0, 1.0)
            self._record_pulse_anim.setKeyValueAt(0.4, 0.4)
            self._record_pulse_anim.setKeyValueAt(1.0, 1.0)

        if active:
            if self._record_pulse_anim.state() != QPropertyAnimation.State.Running:
                self._record_pulse_anim.start()
        else:
            self._record_pulse_anim.stop()
            self._record_pulse_effect.setOpacity(1.0)

    def shutdown(self) -> None:
        if self._record_pulse_anim is not None:
            self._record_pulse_anim.stop()
        if self._record_pulse_effect is not None:
            self._record_pulse_effect.setOpacity(1.0)
        self._anim.stop()
        self._collapse_timer.stop()
