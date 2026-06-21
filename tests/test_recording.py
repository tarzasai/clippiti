from pathlib import Path
import logging
import subprocess

import clippiti.services.recording as recording_mod
from clippiti.services.buffer_engine import SessionRuntime
from clippiti.services.recording import AsyncRecordingService
from clippiti.services.recording import RecordingConfig
from clippiti.services.recording import RecordingService
from clippiti.services.recording import _safe_filename


class _DummyProc:
  pid = 12345

  def __init__(self, poll_value=None):
    self._poll_value = poll_value
    self.returncode = poll_value
    self.terminated = False
    self.killed = False

  def poll(self):
    return self._poll_value

  def terminate(self):
    self.terminated = True

  def wait(self, timeout=None):
    return self.returncode if self.returncode is not None else 0

  def kill(self):
    self.killed = True


def _runtime_with_playlist(playlist_path: Path) -> SessionRuntime:
  return SessionRuntime(
    url="https://example.com/live",
    desired_quality="best",
    stream_title="Title/Live",
    stream_author="Author Name",
    stream_category="Category",
    plugin="example",
    segment_dir=playlist_path.parent,
    playlist_path=playlist_path,
    segment_seconds=5,
    window_segments=12,
  )


def test_safe_filename_sanitizes() -> None:
  assert _safe_filename(" Hello:/World*Test ") == "_Hello__World_Test_"


def test_safe_filename_strips_boundary_underscores() -> None:
  assert _safe_filename("***name***") == "name"


def test_recording_start_generates_sanitized_filename(tmp_path: Path, monkeypatch) -> None:
  playlist = tmp_path / "live.m3u8"
  playlist.write_text("#EXTM3U\n", encoding="utf-8")
  runtime = _runtime_with_playlist(playlist)

  monkeypatch.setattr(recording_mod.time, "strftime", lambda fmt: "20260101_120000")
  monkeypatch.setattr(recording_mod, "_spawn_ffmpeg", lambda cmd, stderr_path: _DummyProc())

  service = RecordingService()
  cfg = RecordingConfig(
    output_dir=tmp_path,
    filename_format="{author}-{timestamp}",
    ffmpeg_path="ffmpeg",
  )

  ts_path = service.start(runtime, cfg)

  assert ts_path.name == "Author_Name-20260101_120000.ts"


def test_recording_start_fails_when_playlist_missing(tmp_path: Path) -> None:
  runtime = _runtime_with_playlist(tmp_path / "missing.m3u8")
  service = RecordingService()
  cfg = RecordingConfig(output_dir=tmp_path)

  try:
    service.start(runtime, cfg)
    assert False
  except RuntimeError as exc:
    assert "playlist" in str(exc)


def test_recording_start_fails_if_already_recording(tmp_path: Path, monkeypatch) -> None:
  playlist = tmp_path / "live.m3u8"
  playlist.write_text("#EXTM3U\n", encoding="utf-8")
  runtime = _runtime_with_playlist(playlist)

  monkeypatch.setattr(recording_mod, "_spawn_ffmpeg", lambda *a, **k: _DummyProc())

  service = RecordingService()
  cfg = RecordingConfig(output_dir=tmp_path)
  service.start(runtime, cfg)

  try:
    service.start(runtime, cfg)
    assert False
  except RuntimeError as exc:
    assert "already in progress" in str(exc)


def test_stop_without_recording_raises() -> None:
  service = RecordingService()
  try:
    service.stop()
    assert False
  except RuntimeError as exc:
    assert "not recording" in str(exc)


def test_finalize_without_remux(tmp_path: Path) -> None:
  service = RecordingService()
  ts_path = tmp_path / "file.ts"
  ts_path.write_text("x", encoding="utf-8")
  cfg = RecordingConfig(output_dir=tmp_path, auto_remux_to_mp4=False)

  final_path, remuxed = service.finalize(ts_path, cfg)

  assert final_path == ts_path
  assert remuxed is False


def test_finalize_with_remux_success(tmp_path: Path, monkeypatch) -> None:
  service = RecordingService()
  ts_path = tmp_path / "file.ts"
  ts_path.write_text("x", encoding="utf-8")
  cfg = RecordingConfig(output_dir=tmp_path, auto_remux_to_mp4=True)

  monkeypatch.setattr(recording_mod, "_remux", lambda *a, **k: True)

  final_path, remuxed = service.finalize(ts_path, cfg)

  assert final_path == tmp_path / "file.mp4"
  assert remuxed is True
  assert not ts_path.exists()


def test_abort_clears_session(tmp_path: Path, monkeypatch) -> None:
  playlist = tmp_path / "live.m3u8"
  playlist.write_text("#EXTM3U\n", encoding="utf-8")
  runtime = _runtime_with_playlist(playlist)

  monkeypatch.setattr(recording_mod, "_spawn_ffmpeg", lambda *a, **k: _DummyProc())
  monkeypatch.setattr(recording_mod, "_graceful_stop", lambda proc: None)

  service = RecordingService()
  cfg = RecordingConfig(output_dir=tmp_path)
  service.start(runtime, cfg)
  service.abort()

  assert service.is_recording() is False


def test_is_recording_false_when_proc_already_exited(tmp_path: Path, monkeypatch) -> None:
  playlist = tmp_path / "live.m3u8"
  playlist.write_text("#EXTM3U\n", encoding="utf-8")
  runtime = _runtime_with_playlist(playlist)

  monkeypatch.setattr(recording_mod, "_spawn_ffmpeg", lambda *a, **k: _DummyProc(poll_value=None))
  service = RecordingService()
  service.start(runtime, RecordingConfig(output_dir=tmp_path))

  assert service.is_recording() is True
  service._session.proc._poll_value = 1
  assert service.is_recording() is False


def test_elapsed_seconds_without_session() -> None:
  service = RecordingService()
  assert service.elapsed_seconds() == 0.0


def test_elapsed_seconds_with_session(tmp_path: Path, monkeypatch) -> None:
  playlist = tmp_path / "live.m3u8"
  playlist.write_text("#EXTM3U\n", encoding="utf-8")
  runtime = _runtime_with_playlist(playlist)

  monkeypatch.setattr(recording_mod, "_spawn_ffmpeg", lambda *a, **k: _DummyProc(poll_value=None))
  monkeypatch.setattr(recording_mod.time, "monotonic", lambda: 105.0)

  service = RecordingService()
  service.start(runtime, RecordingConfig(output_dir=tmp_path))
  service._session.started_at = 100.0
  assert service.elapsed_seconds() == 5.0


def test_graceful_stop_returns_when_already_exited() -> None:
  proc = _DummyProc(poll_value=0)
  recording_mod._graceful_stop(proc)
  assert proc.terminated is False


def test_graceful_stop_kills_when_still_alive() -> None:
  class _P(_DummyProc):
    def __init__(self):
      super().__init__(poll_value=None)
      self._poll_calls = 0

    def poll(self):
      self._poll_calls += 1
      if self._poll_calls >= 3:
        return None
      return None

    def wait(self, timeout=None):
      raise RuntimeError("still running")

  proc = _P()
  recording_mod._graceful_stop(proc)
  assert proc.terminated is True
  assert proc.killed is True


def test_preexec_ignores_failures(monkeypatch) -> None:
  monkeypatch.setattr(recording_mod.ctypes, "CDLL", lambda *_: (_ for _ in ()).throw(RuntimeError("x")))
  recording_mod._preexec()


def test_stderr_log_path_when_debug_disabled(monkeypatch, tmp_path: Path) -> None:
  monkeypatch.setattr(recording_mod.log, "isEnabledFor", lambda *_: False)
  assert recording_mod._stderr_log_path(tmp_path / "x.ts") is None


def test_stderr_log_path_when_debug_enabled(monkeypatch, tmp_path: Path) -> None:
  monkeypatch.setattr(recording_mod.log, "isEnabledFor", lambda *_: True)
  assert recording_mod._stderr_log_path(tmp_path / "x.ts") == tmp_path / "x.stderr.log"


def test_spawn_ffmpeg_uses_stderr_file(monkeypatch, tmp_path: Path) -> None:
  captured = {}

  class _Spawned:
    pid = 999

    def poll(self):
      return None

  def fake_popen(cmd, **kwargs):
    captured["kwargs"] = kwargs
    return _Spawned()

  monkeypatch.setattr(recording_mod.subprocess, "Popen", fake_popen)
  stderr_path = tmp_path / "err.log"
  proc = recording_mod._spawn_ffmpeg(["ffmpeg"], stderr_path)
  assert proc.pid == 999
  assert "stderr" in captured["kwargs"]


def test_remux_failure_returns_false(monkeypatch, tmp_path: Path) -> None:
  src = tmp_path / "in.ts"
  src.write_text("x", encoding="utf-8")
  out = tmp_path / "out.mp4"

  class _Result:
    returncode = 1

  monkeypatch.setattr(recording_mod.subprocess, "run", lambda *a, **k: _Result())
  ok = recording_mod._remux(src, out, "ffmpeg", None)
  assert ok is False


def test_remux_success_returns_true(monkeypatch, tmp_path: Path) -> None:
  src = tmp_path / "in.ts"
  src.write_text("x", encoding="utf-8")
  out = tmp_path / "out.mp4"

  class _Result:
    returncode = 0

  monkeypatch.setattr(recording_mod.subprocess, "run", lambda *a, **k: _Result())
  assert recording_mod._remux(src, out, "ffmpeg", None) is True


def test_remux_exception_returns_false(monkeypatch, tmp_path: Path) -> None:
  src = tmp_path / "in.ts"
  src.write_text("x", encoding="utf-8")
  out = tmp_path / "out.mp4"
  monkeypatch.setattr(recording_mod.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
  assert recording_mod._remux(src, out, "ffmpeg", None) is False


def test_async_request_stop_guard() -> None:
  service = AsyncRecordingService()
  service._stop_in_progress = True
  try:
    assert service.request_stop() is False
  finally:
    service.shutdown()


def test_stop_worker_emits_finished() -> None:
  class _Recording:
    def stop(self):
      return Path("/tmp/out.ts")

  worker = recording_mod._StopWorker(_Recording())
  result = {"value": None}
  worker.finished.connect(lambda value: result.__setitem__("value", value))
  worker.run()
  assert result["value"] == Path("/tmp/out.ts")


def test_stop_worker_emits_failed() -> None:
  class _Recording:
    def stop(self):
      raise RuntimeError("boom")

  worker = recording_mod._StopWorker(_Recording())
  result = {"value": None}
  worker.failed.connect(lambda value: result.__setitem__("value", value))
  worker.run()
  assert isinstance(result["value"], RuntimeError)


def test_async_handle_callbacks_and_delegates(tmp_path: Path) -> None:
  service = AsyncRecordingService()
  try:
    service._stop_in_progress = True
    got_finished = {"v": None}
    got_failed = {"v": None}
    service.stop_finished.connect(lambda value: got_finished.__setitem__("v", value))
    service.stop_failed.connect(lambda value: got_failed.__setitem__("v", value))

    service._handle_stop_finished("done")
    assert service._stop_in_progress is False
    assert got_finished["v"] == "done"

    service._stop_in_progress = True
    service._handle_stop_failed("err")
    assert service._stop_in_progress is False
    assert got_failed["v"] == "err"

    assert service.is_recording() is False
    assert service.elapsed_seconds() == 0.0
    service.abort()
  finally:
    service.shutdown()
