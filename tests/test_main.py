from types import SimpleNamespace

import clippiti.__main__ as main_mod


class _FakeMode:
  def __init__(self, calls: list[tuple[str, str]]) -> None:
    self._calls = calls

  def __enter__(self):
    self._calls.append(("enter", "presenting"))
    return self

  def __exit__(self, exc_type, exc, tb):
    self._calls.append(("exit", "presenting"))
    return False


class _FakeKeep:
  def __init__(self) -> None:
    self.calls: list[tuple[str, str]] = []

  def presenting(self, *, on_fail: str):
    self.calls.append(("presenting", on_fail))
    return _FakeMode(self.calls)

  def running(self, *, on_fail: str):
    self.calls.append(("running", on_fail))
    raise AssertionError("main() should not use keep.running for GUI playback")


def test_main_uses_presenting_wake_lock(monkeypatch, tmp_path) -> None:
  fake_keep = _FakeKeep()
  config = {
    "general": {
      "controls_area": 300,
      "controls_resize_debounce_ms": 40,
      "ffmpeg_path": "ffmpeg",
      "segment_seconds": 5,
      "window_segments": 12,
      "mpv_options": {},
    },
    "streamlink": {"default_args": ""},
    "recording": {"dir": str(tmp_path / "recordings")},
    "clip": {"dir": str(tmp_path / "clips")},
  }

  monkeypatch.setattr(main_mod, "_wakepy_keep", fake_keep)
  monkeypatch.setattr(main_mod, "cleanup_orphan_session_dirs", lambda *_args, **_kwargs: [])
  monkeypatch.setattr(main_mod, "resolve_workdir", lambda *_args, **_kwargs: tmp_path)
  monkeypatch.setattr(main_mod, "resolve_config_path", lambda *_args, **_kwargs: tmp_path / "config.yaml")
  monkeypatch.setattr(main_mod, "load_config", lambda *_args, **_kwargs: config)
  monkeypatch.setattr(main_mod, "normalize_config", lambda value: value)
  monkeypatch.setattr(main_mod, "save_config", lambda *_args, **_kwargs: None)
  monkeypatch.setattr(main_mod, "ensure_output_dirs", lambda *_args, **_kwargs: None)
  monkeypatch.setattr(main_mod, "build_streamlink_command", lambda **_kwargs: ["streamlink", "url", "best"])
  monkeypatch.setattr(main_mod, "build_mpv_options", lambda **_kwargs: {})
  monkeypatch.setattr(
    main_mod,
    "resolve_stream_metadata",
    lambda **_kwargs: SimpleNamespace(plugin="plugin", author="author", category="category", title="title"),
  )

  def fake_run_app(**kwargs):
    assert kwargs["startup_task"] is not None
    return SimpleNamespace(exit_code=0, startup_result=None)

  monkeypatch.setattr(main_mod, "run_app", fake_run_app)

  exit_code = main_mod.main(["https://example.invalid/stream", "best"])

  assert exit_code == 0
  assert fake_keep.calls == [
    ("presenting", "warn"),
    ("enter", "presenting"),
    ("exit", "presenting"),
  ]
