from pathlib import Path
import threading

import clippiti.services.buffer_engine as be
from clippiti.services.buffer_engine import SessionRuntime
from clippiti.services.buffer_engine import StreamMetadata


class _Stdout:
  def close(self):
    return None


class _Proc:
  def __init__(self, poll_values=None, pid=111):
    self._poll_values = list(poll_values or [None])
    self.pid = pid
    self.returncode = None
    self.stdout = _Stdout()
    self.terminated = False
    self.killed = False

  def poll(self):
    if self._poll_values:
      val = self._poll_values.pop(0)
      if val is not None:
        self.returncode = val
      return val
    return self.returncode

  def terminate(self):
    self.terminated = True

  def wait(self, timeout=None):
    if self.returncode is None:
      self.returncode = 0
    return self.returncode

  def kill(self):
    self.killed = True
    self.returncode = -9


def _runtime(tmp_path: Path) -> SessionRuntime:
  return SessionRuntime(
    url="https://example.com/live",
    desired_quality="best",
    stream_title="Title",
    stream_author="Author",
    stream_category="Category",
    plugin="plugin",
    segment_dir=tmp_path / "session",
    playlist_path=tmp_path / "session" / "live.m3u8",
    segment_seconds=5,
    window_segments=12,
  )


def test_buffer_seconds_property() -> None:
  runtime = SessionRuntime(
    url="https://example.com/live",
    desired_quality="best",
    stream_title="Title",
    stream_author="Author",
    stream_category="Category",
    plugin="example",
    segment_dir=Path("/tmp/session"),
    playlist_path=Path("/tmp/session/live.m3u8"),
    segment_seconds=5,
    window_segments=12,
  )
  assert runtime.buffer_seconds == 60


def test_resolve_stream_metadata_success(monkeypatch) -> None:
  class _RunResult:
    returncode = 0
    stderr = ""
    stdout = '{"plugin":"x","metadata":{"author":"a","category":"c","title":"t"}}'

  monkeypatch.setattr(be.subprocess, "run", lambda *a, **k: _RunResult())
  meta = be.resolve_stream_metadata("https://x", "--a 1", "--b 2")
  assert meta.plugin == "x"
  assert meta.author == "a"


def test_resolve_stream_metadata_failure(monkeypatch) -> None:
  class _RunResult:
    returncode = 1
    stderr = "boom"
    stdout = ""

  monkeypatch.setattr(be.subprocess, "run", lambda *a, **k: _RunResult())
  try:
    be.resolve_stream_metadata("https://x", "", "")
    assert False
  except RuntimeError as exc:
    assert "boom" in str(exc)


def test_resolve_stream_metadata_invalid_json(monkeypatch) -> None:
  class _RunResult:
    returncode = 0
    stderr = ""
    stdout = "not-json"

  monkeypatch.setattr(be.subprocess, "run", lambda *a, **k: _RunResult())
  try:
    be.resolve_stream_metadata("https://x", "", "")
    assert False
  except RuntimeError as exc:
    assert "invalid JSON" in str(exc)


def test_start_pipeline_happy_path(tmp_path: Path, monkeypatch) -> None:
  meta = StreamMetadata(plugin="x", author="a", category="c", title="t")

  procs = [_Proc(pid=101), _Proc(pid=102)]

  def fake_popen(cmd, **kwargs):
    proc = procs.pop(0)
    if cmd[0] != "streamlink":
      Path(cmd[-1]).write_text("#EXTM3U\n", encoding="utf-8")
    return proc

  monkeypatch.setattr(be.subprocess, "Popen", fake_popen)
  monkeypatch.setattr(be, "_stderr_log_path", lambda *a, **k: None)

  runtime = be.start_single_session_pipeline(
    workdir=tmp_path,
    ffmpeg_path="ffmpeg",
    url="https://x",
    quality="best",
    streamlink_cmd=["streamlink", "--stdout", "https://x", "best"],
    segment_seconds=5,
    window_segments=12,
    metadata=meta,
  )

  assert runtime.status == "live"
  assert runtime.playlist_path.exists()


def test_start_pipeline_cancel_before_launch(tmp_path: Path) -> None:
  meta = StreamMetadata(plugin="x", author="a", category="c", title="t")
  cancel = threading.Event()
  cancel.set()

  try:
    be.start_single_session_pipeline(
      workdir=tmp_path,
      ffmpeg_path="ffmpeg",
      url="https://x",
      quality="best",
      streamlink_cmd=["streamlink", "--stdout", "https://x", "best"],
      segment_seconds=5,
      window_segments=12,
      metadata=meta,
      cancel_event=cancel,
    )
    assert False
  except RuntimeError as exc:
    assert "cancelled" in str(exc)


def test_terminate_runtime_handles_procs(tmp_path: Path) -> None:
  runtime = _runtime(tmp_path)
  runtime.streamlink_proc = _Proc(poll_values=[None])
  runtime.ffmpeg_proc = _Proc(poll_values=[None])

  be.terminate_runtime(runtime)

  assert runtime.streamlink_proc.terminated is True
  assert runtime.ffmpeg_proc.terminated is True


def test_cleanup_orphan_session_dirs(tmp_path: Path) -> None:
  workdir = tmp_path
  sessions = workdir / "sessions"
  sessions.mkdir(parents=True)

  stale = sessions / "stale"
  stale.mkdir()
  (stale / "owner.pid").write_text("99999\n", encoding="utf-8")

  current = sessions / "current"
  current.mkdir()
  (current / "owner.pid").write_text("123\n", encoding="utf-8")

  removed = be.cleanup_orphan_session_dirs(workdir, current_pid=123)

  assert removed == 1
  assert not stale.exists()
  assert current.exists()


def test_child_process_kwargs_non_posix(monkeypatch) -> None:
  monkeypatch.setattr(be.os, "name", "nt", raising=False)
  kwargs = be._child_process_kwargs()
  assert kwargs == {"text": False}


def test_stderr_target_file(tmp_path: Path) -> None:
  stderr_path = tmp_path / "x.log"
  target, fp = be._stderr_target(stderr_path)
  assert fp is not None
  fp.close()
  assert target is fp


def test_start_pipeline_streamlink_exits_early(tmp_path: Path, monkeypatch) -> None:
  meta = StreamMetadata(plugin="x", author="a", category="c", title="t")
  procs = [_Proc(poll_values=[1], pid=1), _Proc(poll_values=[None], pid=2)]

  def fake_popen(cmd, **kwargs):
    return procs.pop(0)

  monkeypatch.setattr(be.subprocess, "Popen", fake_popen)
  monkeypatch.setattr(be, "_stderr_log_path", lambda *a, **k: None)
  monkeypatch.setattr(be.time, "sleep", lambda *_: None)

  try:
    be.start_single_session_pipeline(
      workdir=tmp_path,
      ffmpeg_path="ffmpeg",
      url="https://x",
      quality="best",
      streamlink_cmd=["streamlink", "--stdout", "https://x", "best"],
      segment_seconds=5,
      window_segments=12,
      metadata=meta,
      startup_timeout_s=1,
    )
    assert False
  except RuntimeError as exc:
    assert "streamlink exited" in str(exc)


def test_start_pipeline_ffmpeg_exits_early(tmp_path: Path, monkeypatch) -> None:
  meta = StreamMetadata(plugin="x", author="a", category="c", title="t")
  procs = [_Proc(poll_values=[None], pid=1), _Proc(poll_values=[2], pid=2)]

  def fake_popen(cmd, **kwargs):
    return procs.pop(0)

  monkeypatch.setattr(be.subprocess, "Popen", fake_popen)
  monkeypatch.setattr(be, "_stderr_log_path", lambda *a, **k: None)
  monkeypatch.setattr(be.time, "sleep", lambda *_: None)

  try:
    be.start_single_session_pipeline(
      workdir=tmp_path,
      ffmpeg_path="ffmpeg",
      url="https://x",
      quality="best",
      streamlink_cmd=["streamlink", "--stdout", "https://x", "best"],
      segment_seconds=5,
      window_segments=12,
      metadata=meta,
      startup_timeout_s=1,
    )
    assert False
  except RuntimeError as exc:
    assert "ffmpeg exited" in str(exc)


def test_start_pipeline_timeout(tmp_path: Path, monkeypatch) -> None:
  meta = StreamMetadata(plugin="x", author="a", category="c", title="t")
  procs = [_Proc(poll_values=[None, None, None], pid=1), _Proc(poll_values=[None, None, None], pid=2)]

  def fake_popen(cmd, **kwargs):
    return procs.pop(0)

  t = {"n": 0.0}

  def fake_monotonic():
    t["n"] += 1.0
    return t["n"]

  monkeypatch.setattr(be.subprocess, "Popen", fake_popen)
  monkeypatch.setattr(be, "_stderr_log_path", lambda *a, **k: None)
  monkeypatch.setattr(be.time, "sleep", lambda *_: None)
  monkeypatch.setattr(be.time, "monotonic", fake_monotonic)

  try:
    be.start_single_session_pipeline(
      workdir=tmp_path,
      ffmpeg_path="ffmpeg",
      url="https://x",
      quality="best",
      streamlink_cmd=["streamlink", "--stdout", "https://x", "best"],
      segment_seconds=5,
      window_segments=12,
      metadata=meta,
      startup_timeout_s=1,
    )
    assert False
  except RuntimeError as exc:
    assert "timed out" in str(exc)


def test_cleanup_runtime_artifacts(tmp_path: Path) -> None:
  runtime = _runtime(tmp_path)
  runtime.segment_dir.mkdir(parents=True)
  (runtime.segment_dir / "x").write_text("x", encoding="utf-8")
  be.cleanup_runtime_artifacts(runtime)
  assert not runtime.segment_dir.exists()


def test_pid_is_alive_false(monkeypatch) -> None:
  monkeypatch.setattr(be.os, "kill", lambda pid, sig: (_ for _ in ()).throw(OSError()))
  assert be._pid_is_alive(123) is False


def test_pid_is_alive_true(monkeypatch) -> None:
  monkeypatch.setattr(be.os, "kill", lambda pid, sig: None)
  assert be._pid_is_alive(99) is True


def test_pid_is_alive_nonpositive() -> None:
  assert be._pid_is_alive(0) is False


def test_resolve_stream_metadata_invalid_shape(monkeypatch) -> None:
  class _RunResult:
    returncode = 0
    stderr = ""
    stdout = "[]"

  monkeypatch.setattr(be.subprocess, "run", lambda *a, **k: _RunResult())
  try:
    be.resolve_stream_metadata("https://x", "", "")
    assert False
  except RuntimeError as exc:
    assert "format" in str(exc)


def test_child_process_kwargs_skips_preexec_in_non_main_thread(monkeypatch) -> None:
  monkeypatch.setattr(be.os, "name", "posix", raising=False)

  class _Thread:
    pass

  monkeypatch.setattr(be.threading, "current_thread", lambda: _Thread())
  monkeypatch.setattr(be.threading, "main_thread", lambda: object())
  kwargs = be._child_process_kwargs()
  assert kwargs == {"text": False}


def test_cleanup_orphan_no_sessions_root(tmp_path: Path) -> None:
  assert be.cleanup_orphan_session_dirs(tmp_path) == 0


def test_cleanup_orphan_keeps_live_owner(tmp_path: Path, monkeypatch) -> None:
  sessions = tmp_path / "sessions"
  sessions.mkdir()
  d = sessions / "live"
  d.mkdir()
  (d / "owner.pid").write_text("222\n", encoding="utf-8")
  monkeypatch.setattr(be, "_pid_is_alive", lambda pid: True)
  removed = be.cleanup_orphan_session_dirs(tmp_path, current_pid=111)
  assert removed == 0
  assert d.exists()


def test_start_pipeline_cancel_while_waiting(tmp_path: Path, monkeypatch) -> None:
  meta = StreamMetadata(plugin="x", author="a", category="c", title="t")
  procs = [_Proc(poll_values=[None, None], pid=1), _Proc(poll_values=[None, None], pid=2)]
  cancel = threading.Event()

  def fake_popen(cmd, **kwargs):
    return procs.pop(0)

  def fake_sleep(_):
    cancel.set()

  monkeypatch.setattr(be.subprocess, "Popen", fake_popen)
  monkeypatch.setattr(be, "_stderr_log_path", lambda *a, **k: None)
  monkeypatch.setattr(be.time, "sleep", fake_sleep)

  try:
    be.start_single_session_pipeline(
      workdir=tmp_path,
      ffmpeg_path="ffmpeg",
      url="https://x",
      quality="best",
      streamlink_cmd=["streamlink", "--stdout", "https://x", "best"],
      segment_seconds=5,
      window_segments=12,
      metadata=meta,
      startup_timeout_s=3,
      cancel_event=cancel,
    )
    assert False
  except RuntimeError as exc:
    assert "cancelled" in str(exc)
