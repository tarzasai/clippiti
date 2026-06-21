from pathlib import Path

from PyQt6.QtCore import QProcess

from clippiti.services.remux_queue import FfmpegJob
from clippiti.services.remux_queue import FfmpegJobQueueService


class _DummyProcess:
  def __init__(self, running: bool = False):
    self._running = running
    self.terminated = False
    self.killed = False
    self.deleted = False

  def state(self):
    if self._running:
      return QProcess.ProcessState.Running
    return QProcess.ProcessState.NotRunning

  def terminate(self):
    self.terminated = True

  def waitForFinished(self, _timeout: int):
    return not self._running

  def kill(self):
    self.killed = True

  def deleteLater(self):
    self.deleted = True


def test_enqueue_returns_target_path(monkeypatch, tmp_path: Path) -> None:
  svc = FfmpegJobQueueService()
  called = {"start": 0}

  monkeypatch.setattr(svc, "_start_next", lambda: called.__setitem__("start", called["start"] + 1))

  job = FfmpegJob(target_path=tmp_path / "out.mp4", ffmpeg_path="ffmpeg")
  result = svc.enqueue(job)

  assert result == tmp_path / "out.mp4"
  assert called["start"] == 1


def test_shutdown_clears_queue_and_active_state() -> None:
  svc = FfmpegJobQueueService()
  svc._queue.append(FfmpegJob(target_path=Path("/tmp/a.mp4"), ffmpeg_path="ffmpeg"))
  svc._active_job = FfmpegJob(target_path=Path("/tmp/b.mp4"), ffmpeg_path="ffmpeg")
  proc = _DummyProcess(running=True)
  svc._active_process = proc
  svc._active_error = "x"

  svc.shutdown()

  assert svc._queue == []
  assert svc._active_job is None
  assert svc._active_process is None
  assert svc._active_error is None
  assert proc.terminated is True


def test_on_process_error_sets_active_error() -> None:
  svc = FfmpegJobQueueService()
  svc._on_process_error(QProcess.ProcessError.FailedToStart)
  assert svc._active_error == "FailedToStart"


def test_on_process_finished_success_removes_source(tmp_path: Path) -> None:
  svc = FfmpegJobQueueService()
  target = tmp_path / "out.mp4"
  source = tmp_path / "in.ts"
  target.write_text("ok", encoding="utf-8")
  source.write_text("x", encoding="utf-8")

  job = FfmpegJob(
    target_path=target,
    ffmpeg_path="ffmpeg",
    source_path=source,
    remove_source_on_success=True,
  )
  proc = _DummyProcess(running=False)

  svc._active_job = job
  svc._active_process = proc
  svc._active_error = None

  svc._on_process_finished(0, QProcess.ExitStatus.NormalExit)

  assert svc._active_job is None
  assert svc._active_process is None
  assert not source.exists()
  assert proc.deleted is True


def test_on_process_finished_failure_sets_default_error(tmp_path: Path) -> None:
  svc = FfmpegJobQueueService()
  job = FfmpegJob(target_path=tmp_path / "missing.mp4", ffmpeg_path="ffmpeg")
  proc = _DummyProcess(running=False)

  svc._active_job = job
  svc._active_process = proc
  svc._active_error = None

  svc._on_process_finished(12, QProcess.ExitStatus.CrashExit)

  assert svc._active_error is None
  assert proc.deleted is True


def test_shutdown_without_active_process_is_noop() -> None:
  svc = FfmpegJobQueueService()
  svc.shutdown()
  assert svc._active_process is None


def test_start_next_returns_when_busy_or_empty() -> None:
  svc = FfmpegJobQueueService()
  svc._active_process = _DummyProcess(running=True)
  svc._start_next()
  assert svc._active_process is not None

  svc._active_process = None
  svc._queue.clear()
  svc._start_next()
  assert svc._active_process is None
