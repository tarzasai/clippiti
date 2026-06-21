"""Video rendering surface backed by libmpv render API."""

import locale
import os
import logging

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QOpenGLContext
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

import mpv

log = logging.getLogger("clippiti.ui.video_surface")

# libmpv requires C numeric locale (decimal dot) and can crash otherwise.
os.environ["LC_NUMERIC"] = "C"
locale.setlocale(locale.LC_NUMERIC, "C")


class VideoSurface(QOpenGLWidget):
  frame_ready = pyqtSignal()
  DEFAULT_VOLUME = 70

  def __init__(
    self,
    media_source: str | None,
    mpv_options: dict[str, object],
    start_seconds: int = 0,
  ) -> None:
    super().__init__()
    self.setObjectName("video-surface")
    self._media_source = media_source
    self._start_seconds = max(0, int(start_seconds))
    self._mpv_options = dict(mpv_options)
    self._shutting_down = False
    self._volume = self.DEFAULT_VOLUME
    self._muted = False

    self.player: mpv.MPV | None = None
    self.render_ctx: mpv.MpvRenderContext | None = None
    self._gl_proc_addr: mpv.MpvGlGetProcAddressFn | None = None
    self.frame_ready.connect(self._maybe_paint_next_frame)

  @property
  def volume(self) -> int:
    return self._volume

  @volume.setter
  def volume(self, value: int) -> None:
    self._volume = max(0, min(100, int(value)))
    if self.player is not None:
      self.player.volume = self._volume

  @property
  def muted(self) -> bool:
    return self._muted

  @muted.setter
  def muted(self, value: bool) -> None:
    self._muted = bool(value)
    if self.player is not None:
      self.player.mute = self._muted

  def shutdown(self) -> None:
    if self._shutting_down:
      return
    self._shutting_down = True
    log.debug("video: shutdown begin")

    try:
      try:
        self.frame_ready.disconnect(self._maybe_paint_next_frame)
      except Exception:
        pass
      else:
        log.debug("video: frame callback disconnected")

      if self.render_ctx is not None:
        # Stop render callback first to avoid cross-thread updates while Qt tears down GL resources.
        self.render_ctx.update_cb = None
        log.debug("video: render callback cleared")
        try:
          self.makeCurrent()
          self.render_ctx.free()
          log.debug("video: render context freed")
        except Exception:
          log.exception("video: failed to free render context")
        finally:
          try:
            self.doneCurrent()
          except Exception:
            log.exception("video: failed to release GL context")

      if self.player is not None:
        try:
          self.player.terminate()
          log.info("video: mpv terminated")
        except Exception:
          log.exception("video: failed to terminate mpv")
    finally:
      self.render_ctx = None
      self.player = None
      self._gl_proc_addr = None
      log.info("video: shutdown complete")

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

    locale.setlocale(locale.LC_NUMERIC, "C")

    player_options = dict(self._mpv_options)
    player_options["start"] = self._start_seconds
    player_options["volume"] = self._volume
    player_options["mute"] = self._muted
    player_options["audio_client_name"] = "Clippiti"

    self.player = mpv.MPV(**player_options)

    self._gl_proc_addr = mpv.MpvGlGetProcAddressFn(self._get_proc_addr)
    self.render_ctx = mpv.MpvRenderContext(
      self.player,
      "opengl",
      opengl_init_params={"get_proc_address": self._gl_proc_addr},
      advanced_control=True,
    )
    self.render_ctx.update_cb = self.frame_ready.emit

    if self._media_source:
      self._play_media_source(self._media_source)

  def set_media_source(self, media_source: str) -> None:
    self._media_source = media_source
    if self.player is None or self._shutting_down:
      return
    self._play_media_source(media_source)

  def _play_media_source(self, media_source: str) -> None:
    if self.player is None:
      return
    if not media_source:
      return
    try:
      self.player.play(media_source)
      log.debug("video: play requested source=%s", media_source)
    except Exception:
      # Keep app shell alive even if media cannot be opened yet.
      log.exception("video: failed to start playback source=%s", media_source)

  def _maybe_paint_next_frame(self) -> None:
    if self._shutting_down:
      return
    if self.render_ctx is None:
      return
    if self.render_ctx.update():
      self.update()

  def paintGL(self) -> None:  # noqa: N802
    if self._shutting_down:
      return
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
    self.shutdown()
    super().closeEvent(event)
