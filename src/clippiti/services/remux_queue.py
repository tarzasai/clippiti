"""Queued remux service using Qt signals and QProcess."""

from dataclasses import dataclass
from pathlib import Path
import logging

from PyQt6.QtCore import QObject, QProcess, pyqtSignal


log = logging.getLogger("clippiti.services.remux_queue")


@dataclass
class RemuxJob:
    source_path: Path
    target_path: Path
    ffmpeg_path: str
    remove_source_on_success: bool = True
    stderr_path: Path | None = None
    kind: str = "recording"


@dataclass
class RemuxJobResult:
    job: RemuxJob
    success: bool
    exit_code: int
    error: str | None = None


class RemuxQueueService(QObject):
    job_started = pyqtSignal(object)
    job_finished = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue: list[RemuxJob] = []
        self._active_job: RemuxJob | None = None
        self._active_process: QProcess | None = None
        self._active_error: str | None = None
        self._shutting_down = False

    def enqueue(self, job: RemuxJob) -> Path:
        self._queue.append(job)
        if self._active_process is None:
            self._start_next()
        return job.target_path

    def shutdown(self) -> None:
        self._shutting_down = True
        self._queue.clear()

        process = self._active_process
        self._active_process = None
        self._active_job = None
        self._active_error = None

        if process is None:
            return

        if process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
            if not process.waitForFinished(1000):
                process.kill()
                process.waitForFinished(1000)
        process.deleteLater()

    def _start_next(self) -> None:
        if self._active_process is not None:
            return
        if not self._queue:
            return

        job = self._queue.pop(0)
        process = QProcess(self)
        process.setProgram(job.ffmpeg_path)
        process.setArguments([
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(job.source_path),
            "-c",
            "copy",
            str(job.target_path),
        ])
        process.setStandardOutputFile(QProcess.nullDevice())
        if job.stderr_path is not None:
            process.setStandardErrorFile(str(job.stderr_path))
        else:
            process.setStandardErrorFile(QProcess.nullDevice())

        process.finished.connect(self._on_process_finished)
        process.errorOccurred.connect(self._on_process_error)

        self._active_job = job
        self._active_process = process
        self._active_error = None
        self.job_started.emit(job)
        process.start()

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        self._active_error = error.name

    def _on_process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        job = self._active_job
        process = self._active_process

        if job is None or process is None:
            return

        self._active_job = None
        self._active_process = None

        success = exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0 and job.target_path.exists()
        error = self._active_error
        if not success and error is None:
            error = f"exit_code={exit_code}"

        if success and job.remove_source_on_success:
            job.source_path.unlink(missing_ok=True)

        result = RemuxJobResult(job=job, success=success, exit_code=exit_code, error=error)
        self.job_finished.emit(result)

        process.deleteLater()
        self._active_error = None

        if not self._shutting_down:
            self._start_next()
