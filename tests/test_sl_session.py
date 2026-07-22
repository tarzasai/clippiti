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

  assert bytes(stdin.data) == b"preonetwo"
  assert pump.poll() == 0
  assert pump.error is None
  assert stdin.closed is True
  assert fd.closed is True


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
