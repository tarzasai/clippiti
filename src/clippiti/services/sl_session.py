"""In-process Streamlink integration.

This module owns:

- a persistent :class:`Streamlink` session,
- a non-interactive user-input requester (Clippiti has no console prompt),
- parsing of Streamlink arguments through Streamlink's own CLI argument parser
  (so behavior matches the real `streamlink` command exactly),
- resolving a URL + quality to a ready-to-open stream plus its metadata,
- a background pump that reads stream bytes and writes them to ffmpeg's stdin.
"""

from dataclasses import dataclass
import errno
import logging
import threading

from streamlink import Streamlink
from streamlink.exceptions import NoPluginError, PluginError, StreamError
from streamlink.stream.stream import Stream, StreamIO
from streamlink.user_input import UserInputRequester
from streamlink_cli.argparser import (
  build_parser,
  setup_plugin_args,
  setup_plugin_options,
  setup_session_options,
)
from streamlink_cli.constants import PLUGIN_DIRS

log = logging.getLogger("clippiti")

# errno values that mean "the reader (ffmpeg) went away", not a real stream error.
_ACCEPTABLE_ERRNO = (errno.EPIPE, errno.EINVAL, errno.ECONNRESET)


@dataclass
class StreamMetadata:
  plugin: str
  author: str
  category: str
  title: str


@dataclass
class ResolvedStream:
  metadata: StreamMetadata
  stream: Stream
  quality: str
  available: list[str]


class NonInteractiveUserInputRequester(UserInputRequester):
  """Fail clearly instead of prompting. Clippiti has no interactive console."""

  def ask(self, prompt: str) -> str:
    raise OSError(
      f"Streamlink requested interactive input ({prompt!r}), which Clippiti does not support. "
      "Provide the value through Streamlink arguments (after '--') or the config file instead."
    )

  def ask_password(self, prompt: str) -> str:
    raise OSError(
      f"Streamlink requested a password ({prompt!r}), which Clippiti does not support. "
      "Provide credentials through Streamlink arguments (after '--') or the config file instead."
    )


def create_session() -> Streamlink:
  """Create a single reusable Streamlink session with built-in plugins loaded.

  User-provided ("sideloaded") plugins are loaded from Streamlink's standard
  plugin directories, matching the behavior of the ``streamlink`` command so a
  custom plugin dropped into e.g. ``~/.local/share/streamlink/plugins`` works.
  """
  session = Streamlink({"user-input-requester": NonInteractiveUserInputRequester()})
  _load_sideloaded_plugins(session)
  return session


def _load_sideloaded_plugins(session: Streamlink) -> None:
  for directory in PLUGIN_DIRS:
    if not directory.is_dir():
      continue
    try:
      if session.plugins.load_path(directory):
        log.debug("streamlink: sideloaded plugins from %s", directory)
    except Exception:
      log.debug("streamlink: failed to load plugins from %s", directory, exc_info=True)


def parse_streamlink_tokens(session: Streamlink, tokens: list[str]):
  """Parse Streamlink option tokens using Streamlink's own CLI parser.

  Plugin-specific arguments are registered first so that plugin flags are
  recognized. Unknown flags raise a clear ``RuntimeError`` instead of dumping
  Streamlink's full usage text.
  """
  parser = build_parser()
  setup_plugin_args(session, parser)

  try:
    args, extras = parser.parse_known_args(tokens)
  except SystemExit as exc:
    raise RuntimeError("invalid Streamlink arguments") from exc

  if extras:
    raise RuntimeError(f"unrecognized Streamlink arguments: {' '.join(extras)}")

  return args


def resolve_stream(
  session: Streamlink,
  url: str,
  quality: str,
  tokens: list[str],
) -> ResolvedStream:
  """Resolve a URL + quality to a ready-to-open stream and its metadata.

  This performs the network plugin probe once; the returned :class:`Stream`
  should later be opened with :func:`open_stream` on the thread that consumes it.
  """
  args = parse_streamlink_tokens(session, tokens)

  try:
    setup_session_options(session, args)
  except Exception as exc:
    raise RuntimeError(f"failed to apply Streamlink options: {exc}") from exc

  try:
    pluginname, pluginclass, resolved_url = session.resolve_url(url)
  except NoPluginError:
    raise RuntimeError(f"no Streamlink plugin can handle URL: {url}") from None
  except PluginError as exc:
    raise RuntimeError(str(exc)) from exc

  try:
    options = setup_plugin_options(session, args, pluginname, pluginclass)
  except Exception as exc:
    raise RuntimeError(f"failed to apply Streamlink plugin options: {exc}") from exc

  plugin = pluginclass(session, resolved_url, options)

  log.debug("streamlink: resolved plugin=%s url=%s", pluginname, resolved_url)

  try:
    streams = plugin.streams()
  except PluginError as exc:
    raise RuntimeError(str(exc)) from exc

  if not streams:
    raise RuntimeError(f"no playable streams found on this URL: {url}")

  # Streamlink accepts a comma-separated priority list, e.g. "720p,best": each
  # candidate is tried in order and the first available one is used.
  candidates = [part.strip().lower() for part in quality.split(",") if part.strip()]
  if not candidates:
    candidates = ["best"]

  chosen = next((cand for cand in candidates if cand in streams), None)
  if chosen is None:
    available = ", ".join(sorted(streams))
    raise RuntimeError(f"quality {quality!r} is not available. Available: {available}")

  meta = plugin.get_metadata()
  metadata = StreamMetadata(
    plugin=pluginname or "unknown",
    author=str(meta.get("author") or "unknown"),
    category=str(meta.get("category") or "unknown"),
    title=str(meta.get("title") or url),
  )

  log.debug(
    "streamlink: metadata plugin=%s author=%s category=%s title=%s",
    metadata.plugin,
    metadata.author,
    metadata.category,
    metadata.title,
  )

  return ResolvedStream(
    metadata=metadata,
    stream=streams[chosen],
    quality=chosen,
    available=sorted(streams),
  )


def open_stream(stream: Stream, prebuffer_size: int = 8192) -> tuple[StreamIO, bytes]:
  """Open a stream and read an initial chunk to fail fast on empty/broken streams.

  Returns the open stream file object and the already-read prebuffer bytes, which
  the caller must write to the output before continuing to pump.
  """
  try:
    stream_fd = stream.open()
  except StreamError as exc:
    raise RuntimeError(f"could not open stream: {exc}") from exc

  try:
    prebuffer = stream_fd.read(prebuffer_size)
  except OSError as exc:
    stream_fd.close()
    raise RuntimeError(f"failed to read data from stream: {exc}") from exc

  if not prebuffer:
    stream_fd.close()
    raise RuntimeError("no data returned from stream")

  return stream_fd, prebuffer


class StreamPump:
  """Reads bytes from a Streamlink stream and writes them to ffmpeg's stdin.

  Exposes a :meth:`poll`/:attr:`returncode` interface compatible with the
  pipeline health check so callers can treat it like a subprocess handle.
  """

  def __init__(
    self,
    stream_fd: StreamIO,
    ffmpeg_stdin,
    prebuffer: bytes = b"",
    chunk_size: int = 8192,
  ) -> None:
    self._fd = stream_fd
    self._stdin = ffmpeg_stdin
    self._prebuffer = prebuffer
    self._chunk_size = chunk_size
    self._stop = threading.Event()
    self._thread = threading.Thread(target=self._run, name="clippiti-stream-pump", daemon=True)
    self.error: str | None = None
    self.returncode: int | None = None

  def start(self) -> None:
    self._thread.start()

  def _run(self) -> None:
    read = self._fd.read
    write = self._stdin.write
    try:
      if self._prebuffer:
        write(self._prebuffer)
        self._prebuffer = b""
      while not self._stop.is_set():
        data = read(self._chunk_size)
        if data == b"":
          break
        write(data)
    except OSError as exc:
      if getattr(exc, "errno", None) in _ACCEPTABLE_ERRNO:
        log.debug("stream pump: output closed (%s)", exc)
      else:
        self.error = str(exc)
        log.debug("stream pump: read/write error: %s", exc, exc_info=True)
    except Exception as exc:  # pragma: no cover - defensive
      self.error = str(exc)
      log.debug("stream pump: unexpected error: %s", exc, exc_info=True)
    finally:
      self.returncode = 1 if self.error else 0
      try:
        self._stdin.close()
      except Exception:
        pass
      try:
        self._fd.close()
      except Exception:
        pass

  def poll(self) -> int | None:
    """Return ``None`` while pumping, or an exit-like code once finished."""
    return self.returncode

  def is_alive(self) -> bool:
    return self._thread.is_alive()

  def stop(self, timeout: float = 3.0) -> None:
    self._stop.set()
    # Closing the stream fd unblocks a pending read().
    try:
      self._fd.close()
    except Exception:
      pass
    if self._thread.is_alive():
      self._thread.join(timeout=timeout)
