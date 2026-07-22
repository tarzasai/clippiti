"""Video rendering surface backed by libmpv render API."""

import locale
import os
import logging
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QOpenGLContext
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

import mpv

log = logging.getLogger("clippiti")

# libmpv requires C numeric locale (decimal dot) and can crash otherwise.
os.environ["LC_NUMERIC"] = "C"
locale.setlocale(locale.LC_NUMERIC, "C")


class VideoSurface(QOpenGLWidget):
  frame_ready = pyqtSignal()
  DEFAULT_VOLUME = 70
  ROTATION_STEP = 90

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
    self._rotation = 0
    self._screenshot_futures: set = set()

    self.player: mpv.MPV | None = None
    self.render_ctx: mpv.MpvRenderContext | None = None
    self._gl_proc_addr: mpv.MpvGlGetProcAddressFn | None = None
    self._on_file_loaded_cb = None
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
    # Render screenshots with mpv's software scaler instead of the libmpv render
    # VO. The render-VO screenshot path drops chroma (sepia) when video-rotate is
    # active; the SW path handles rotation correctly. Playback is unaffected
    # (still hardware-decoded and GPU-rendered).
    player_options["screenshot_sw"] = "yes"

    self.player = mpv.MPV(**player_options)
    self._install_decoder_logging()

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

  def _install_decoder_logging(self) -> None:
    if self.player is None:
      return

    try:
      self.player.observe_property("hwdec-current", self._on_hwdec_current_changed)
    except Exception:
      log.exception("video: failed to observe hwdec-current")

    try:
      @self.player.event_callback("file-loaded")
      def _on_file_loaded(_event) -> None:
        self._log_decoder_status("file-loaded")

      self._on_file_loaded_cb = _on_file_loaded
    except Exception:
      log.exception("video: failed to install file-loaded callback")

  def _on_hwdec_current_changed(self, _name: str, value: object) -> None:
    mode = str(value or "")
    using_hw = mode not in {"", "no", "none"}
    path = "GPU" if using_hw else "CPU"
    log.info("video: decode path=%s hwdec-current=%s", path, mode or "none")

  def _log_decoder_status(self, context: str) -> None:
    if self.player is None:
      return

    hwdec_current = "unknown"
    video_codec = "unknown"
    decoder_desc = "unknown"

    try:
      hwdec_current = str(getattr(self.player, "hwdec_current", "") or "none")
    except Exception:
      pass

    try:
      video_codec = str(getattr(self.player, "video_codec", "") or "unknown")
    except Exception:
      pass

    try:
      decoder_desc = str(getattr(self.player, "decoder_desc", "") or "unknown")
    except Exception:
      pass

    using_hw = hwdec_current not in {"", "no", "none", "unknown"}
    path = "GPU" if using_hw else "CPU"
    log.info(
      "video: %s decode path=%s hwdec-current=%s codec=%s decoder=%s",
      context,
      path,
      hwdec_current,
      video_codec,
      decoder_desc,
    )

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

  def rotate_clockwise(self) -> int:
    if self.player is None:
      return 0

    new_rotation = (self._rotation + self.ROTATION_STEP) % 360
    try:
      self.player.video_rotate = new_rotation
      log.debug("video: rotation set to %s", new_rotation)
    except Exception:
      log.exception("video: failed to set rotation=%s", new_rotation)
      return self._rotation
    self._rotation = new_rotation
    return new_rotation

  def toggle_flip_horizontal(self) -> bool:
    if self.player is None:
      return False

    try:
      self.player.command("vf", "toggle", "hflip")
      log.debug("video: hflip toggled")
      return True
    except Exception:
      log.exception("video: failed to toggle hflip")
      return False

  def current_rotation(self) -> int:
    """Return the active clockwise display rotation in degrees (0-359).

    Tracked in Python state rather than read back from mpv, because reading
    ``video-rotate`` immediately after setting it can return the previous value
    (the change lands on mpv's next playloop tick), which left the first
    snapshot after a rotation un-rotated.
    """
    return self._rotation

  def save_screenshot(self, path: Path, on_done) -> bool:
    """Asynchronously save mpv's current video frame to ``path``.

    MUST use command_async: a synchronous screenshot deadlocks with the libmpv
    render API, because the screenshot needs the render loop -- which runs on
    this same GUI thread -- so a blocking call freezes the whole app.
    ``on_done(success: bool)`` is invoked on mpv's event thread when done.
    Rotation is intentionally not applied here yet.
    """
    if self.player is None:
      return False

    def _cb(error, result) -> None:
      ok = error is None and path.exists()
      try:
        on_done(ok)
      finally:
        try:
          self._screenshot_futures.discard(future)
        except NameError:
          pass

    try:
      future = self.player.command_async(
        "screenshot-to-file", str(path), "video", callback=_cb
      )
    except Exception:
      log.exception("video: screenshot failed path=%s", path)
      return False
    self._screenshot_futures.add(future)
    return True

  def live_lag_seconds(self) -> float | None:
    """Return how far behind the live edge the player is currently displaying.

    Computed as the gap between the end of mpv's demuxer cache and the current
    playback position, both in the same timeline. Used to locate the on-screen
    frame within the buffered segments for snapshots.
    """
    if self.player is None:
      return None
    try:
      position = self.player.time_pos
      cache_end = self.player.demuxer_cache_time
    except Exception:
      return None
    if position is None or cache_end is None:
      return None
    lag = float(cache_end) - float(position)
    return lag if lag > 0 else 0.0

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
