import errno
import threading
import time

import pytest

import clippiti.services.slsession as ss
from clippiti.services.slsession import (
  NonInteractiveUserInputRequester,
  StreamMetadata,
  StreamPump,
)


class _FakeFd:
  def __init__(self, chunks) -> None:
    self._chunks = list(chunks)
    self.closed = False

  def read(self, size):
    if self._chunks:
      return self._chunks.pop(0)
    return b""

  def close(self):
    self.closed = True


class _FakeStdin:
  def __init__(self) -> None:
    self.data = bytearray()
    self.closed = False

  def write(self, chunk):
    self.data.extend(chunk)

  def close(self):
    self.closed = True


class _FakePlugin:
  def __init__(self, streams, metadata) -> None:
    self._streams = streams
    self._metadata = metadata

  def streams(self, *a, **k):
    return self._streams

  def get_metadata(self):
    return self._metadata


class _FakePluginClass:
  def __init__(self, plugin) -> None:
    self._plugin = plugin

  def __call__(self, session, url, options):
    return self._plugin


class _FakeSession:
  def __init__(self, pluginclass) -> None:
    self._pluginclass = pluginclass

  def resolve_url(self, url):
    return "twitch", self._pluginclass, url


def _patch_parse(monkeypatch):
  monkeypatch.setattr(ss, "parse_streamlink_tokens", lambda session, tokens: object())
  monkeypatch.setattr(ss, "setup_session_options", lambda session, args: None)
  monkeypatch.setattr(ss, "setup_plugin_options", lambda *a, **k: object())


def test_streamlink_config_tokens(monkeypatch, tmp_path) -> None:
  main_cfg = tmp_path / "config"
  main_cfg.write_text("hls-live-edge=6\n", encoding="utf-8")
  plugin_cfg = tmp_path / "config.twitch"
  plugin_cfg.write_text("twitch-disable-ads\n", encoding="utf-8")
  monkeypatch.setattr(ss, "CONFIG_FILES", [main_cfg])

  tokens = ss._streamlink_config_tokens("twitch", [])
  assert tokens == [f"@{main_cfg}", f"@{plugin_cfg}"]


def test_streamlink_config_tokens_no_plugin_config(monkeypatch, tmp_path) -> None:
  main_cfg = tmp_path / "config"
  main_cfg.write_text("hls-live-edge=6\n", encoding="utf-8")
  monkeypatch.setattr(ss, "CONFIG_FILES", [main_cfg])

  tokens = ss._streamlink_config_tokens("twitch", [])
  assert tokens == [f"@{main_cfg}"]


def test_streamlink_config_tokens_no_config_flag(monkeypatch, tmp_path) -> None:
  main_cfg = tmp_path / "config"
  main_cfg.write_text("hls-live-edge=6\n", encoding="utf-8")
  monkeypatch.setattr(ss, "CONFIG_FILES", [main_cfg])

  assert ss._streamlink_config_tokens("twitch", ["--no-config"]) == []


def test_streamlink_config_tokens_none_present(monkeypatch, tmp_path) -> None:
  monkeypatch.setattr(ss, "CONFIG_FILES", [tmp_path / "config"])
  assert ss._streamlink_config_tokens("twitch", []) == []


def test_user_input_requester_ask_raises() -> None:
  req = NonInteractiveUserInputRequester()
  with pytest.raises(OSError):
    req.ask("username?")
  with pytest.raises(OSError):
    req.ask_password("password?")


def test_resolve_stream_success(monkeypatch) -> None:
  _patch_parse(monkeypatch)
  streams = {"best": object(), "worst": object()}
  metadata = {"author": "streamer", "category": "Just Chatting", "title": "hello"}
  plugin = _FakePlugin(streams, metadata)
  session = _FakeSession(_FakePluginClass(plugin))

  resolved = ss.resolve_stream(session, "https://twitch.tv/x", "best", [])

  assert resolved.stream is streams["best"]
  assert resolved.quality == "best"
  assert isinstance(resolved.metadata, StreamMetadata)
  assert resolved.metadata.plugin == "twitch"
  assert resolved.metadata.author == "streamer"
  assert resolved.available == ["best", "worst"]


def test_resolve_stream_quality_missing(monkeypatch) -> None:
  _patch_parse(monkeypatch)
  streams = {"720p": object(), "480p": object()}
  plugin = _FakePlugin(streams, {})
  session = _FakeSession(_FakePluginClass(plugin))

  with pytest.raises(RuntimeError) as exc:
    ss.resolve_stream(session, "https://twitch.tv/x", "best", [])
  assert "not available" in str(exc.value)


def test_resolve_stream_quality_fallback_list(monkeypatch) -> None:
  _patch_parse(monkeypatch)
  streams = {"480p": object(), "best": object()}
  plugin = _FakePlugin(streams, {})
  session = _FakeSession(_FakePluginClass(plugin))

  # 720p is unavailable, so it falls back to best.
  resolved = ss.resolve_stream(session, "https://twitch.tv/x", "720p,best", [])
  assert resolved.quality == "best"
  assert resolved.stream is streams["best"]


def test_resolve_stream_quality_fallback_first_wins(monkeypatch) -> None:
  _patch_parse(monkeypatch)
  streams = {"720p": object(), "480p": object(), "best": object()}
  plugin = _FakePlugin(streams, {})
  session = _FakeSession(_FakePluginClass(plugin))

  resolved = ss.resolve_stream(session, "https://twitch.tv/x", "720p, best", [])
  assert resolved.quality == "720p"
  assert resolved.stream is streams["720p"]


def test_resolve_stream_quality_list_none_available(monkeypatch) -> None:
  _patch_parse(monkeypatch)
  streams = {"1080p": object(), "worst": object()}
  plugin = _FakePlugin(streams, {})
  session = _FakeSession(_FakePluginClass(plugin))

  with pytest.raises(RuntimeError) as exc:
    ss.resolve_stream(session, "https://twitch.tv/x", "720p,480p", [])
  assert "not available" in str(exc.value)


def test_resolve_stream_no_streams(monkeypatch) -> None:
  _patch_parse(monkeypatch)
  plugin = _FakePlugin({}, {})
  session = _FakeSession(_FakePluginClass(plugin))

  with pytest.raises(RuntimeError) as exc:
    ss.resolve_stream(session, "https://twitch.tv/x", "best", [])
  assert "no playable streams" in str(exc.value).lower()


def test_resolve_stream_metadata_defaults(monkeypatch) -> None:
  _patch_parse(monkeypatch)
  streams = {"best": object()}
  plugin = _FakePlugin(streams, {"author": None, "category": None, "title": None})
  session = _FakeSession(_FakePluginClass(plugin))

  resolved = ss.resolve_stream(session, "https://twitch.tv/x", "best", [])
  assert resolved.metadata.author == "unknown"
  assert resolved.metadata.category == "unknown"
  assert resolved.metadata.title == "https://twitch.tv/x"


def test_open_stream_reads_prebuffer() -> None:
  class _Stream:
    def open(self):
      return _FakeFd([b"abc"])

  fd, prebuffer = ss.open_stream(_Stream())
  assert prebuffer == b"abc"
  fd.close()


def test_open_stream_empty_raises() -> None:
  class _Stream:
    def open(self):
      return _FakeFd([])

  with pytest.raises(RuntimeError) as exc:
    ss.open_stream(_Stream())
  assert "no data" in str(exc.value).lower()


def test_stream_pump_pumps_bytes_and_closes() -> None:
  fd = _FakeFd([b"one", b"two"])
  stdin = _FakeStdin()
  pump = StreamPump(fd, stdin, prebuffer=b"pre")
  pump.start()
  pump._thread.join(timeout=2.0)
  pump.stop()

  assert bytes(stdin.data) == b"preonetwo"
  assert pump.poll() == 0
  assert pump.error is None
  assert stdin.closed is True
  assert fd.closed is True
  assert pump.close_pending is False


def test_stream_pump_stop_does_not_block_on_slow_close() -> None:
  release = threading.Event()

  class _BlockingCloseFd(_FakeFd):
    def close(self):
      release.wait(timeout=5.0)
      super().close()

  fd = _BlockingCloseFd([b"one"])
  pump = StreamPump(fd, _FakeStdin())
  pump.start()
  pump._thread.join(timeout=2.0)

  started = time.monotonic()
  pump.stop(timeout=0.2)
  assert time.monotonic() - started < 1.0
  assert pump.close_pending is True
  assert pump.poll() == 0

  release.set()
  pump._close_async(fd).join(timeout=2.0)
  assert pump.close_pending is False
  assert fd.closed is True


def _run_pump(pump: StreamPump) -> None:
  pump.start()
  pump._thread.join(timeout=5.0)
  assert not pump.is_alive()


def test_stream_pump_reconnects_after_eof() -> None:
  first = _FakeFd([b"one"])
  second = _FakeFd([b"three"])
  stdin = _FakeStdin()
  reopened = []

  def reopen():
    reopened.append(True)
    if len(reopened) == 1:
      return second, b"two"
    raise ss.StreamOfflineError("offline")

  pump = StreamPump(first, stdin, reopen=reopen)
  _run_pump(pump)

  assert bytes(stdin.data) == b"onetwothree"
  assert pump.reconnect_count == 1
  assert pump.poll() == 0
  assert pump.error is None
  assert first.closed is True
  assert second.closed is True


def test_stream_pump_retries_transient_reopen_failures() -> None:
  attempts = []
  stdin = _FakeStdin()

  def reopen():
    attempts.append(True)
    if len(attempts) < 3:
      raise RuntimeError("network down")
    if len(attempts) == 3:
      return _FakeFd([b"b"]), b""
    raise ss.StreamOfflineError("offline")

  pump = StreamPump(_FakeFd([b"a"]), stdin, reopen=reopen, reconnect_max_delay_s=0.01)
  pump._stop.wait = lambda timeout=None: False
  _run_pump(pump)

  assert bytes(stdin.data) == b"ab"
  assert len(attempts) == 4
  assert pump.reconnect_count == 1
  assert pump.poll() == 0


def test_stream_pump_gives_up_after_reconnect_window() -> None:
  def reopen():
    raise RuntimeError("network down")

  pump = StreamPump(_FakeFd([b"a"]), _FakeStdin(), reopen=reopen, reconnect_window_s=0.0)
  _run_pump(pump)

  assert pump.poll() == 1
  assert "network down" in (pump.error or "")
  assert pump.reconnecting is False


def test_stream_pump_no_reconnect_when_output_closed() -> None:
  class _BrokenStdin(_FakeStdin):
    def write(self, chunk):
      raise BrokenPipeError(errno.EPIPE, "broken pipe")

  def reopen():
    raise AssertionError("must not reconnect")

  pump = StreamPump(_FakeFd([b"a"]), _BrokenStdin(), reopen=reopen)
  _run_pump(pump)

  assert pump.poll() == 0


def test_stream_pump_stop_during_reconnect_closes_new_stream() -> None:
  new_fd = _FakeFd([b"late"])
  entered = threading.Event()
  proceed = threading.Event()

  def reopen():
    entered.set()
    proceed.wait(timeout=5.0)
    return new_fd, b""

  stdin = _FakeStdin()
  pump = StreamPump(_FakeFd([b"a"]), stdin, reopen=reopen)
  pump.start()
  assert entered.wait(timeout=2.0)
  assert pump.reconnecting is True

  pump._stop.set()
  proceed.set()
  pump._thread.join(timeout=2.0)
  pump._close_async(new_fd).join(timeout=2.0)

  assert bytes(stdin.data) == b"a"
  assert new_fd.closed is True
  assert pump.reconnect_count == 0


def test_resolve_stream_fatal_plugin_error_is_offline(monkeypatch) -> None:
  from streamlink.exceptions import FatalPluginError

  class _OfflinePlugin(_FakePlugin):
    def streams(self, *a, **k):
      raise FatalPluginError("Room is offline")

  session = _FakeSession(_FakePluginClass(_OfflinePlugin({}, {})))
  _patch_parse(monkeypatch)

  with pytest.raises(ss.StreamOfflineError):
    ss.resolve_stream(session, "https://twitch.tv/x", "best", [])


def test_stream_pump_output_closed_is_not_error() -> None:
  fd = _FakeFd([b"data"])

  class _BrokenStdin:
    def __init__(self):
      self.closed = False

    def write(self, chunk):
      err = OSError("broken pipe")
      import errno
      err.errno = errno.EPIPE
      raise err

    def close(self):
      self.closed = True

  pump = StreamPump(fd, _BrokenStdin(), prebuffer=b"x")
  pump.start()
  pump._thread.join(timeout=2.0)

  assert pump.error is None
  assert pump.poll() == 0


def test_parse_streamlink_tokens_unknown_flag(monkeypatch) -> None:
  session = ss.create_session()
  with pytest.raises(RuntimeError) as exc:
    ss.parse_streamlink_tokens(session, ["--definitely-not-a-flag", "value"])
  assert "unrecognized" in str(exc.value).lower()
