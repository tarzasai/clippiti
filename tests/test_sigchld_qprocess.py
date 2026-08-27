"""Local-only regression test for the SIGCHLD / QProcess clip-export fix.

This spawns a *real* QProcess (the same mechanism the clip export uses) while
SIGCHLD is set to SIG_IGN — the disposition clippiti inherits when launched by a
parent launcher such as lurkiti. Under SIG_IGN Qt cannot reap its child, so it
reports a crash and clip export was wrongly flagged as failed. The fix,
``reset_child_signal_disposition``, restores SIG_DFL so reaping works again.

It is skipped on CI (real subprocess reaping under mutated signal state is exactly
the kind of environment-sensitive behaviour we don't want gating PRs) and on any
platform without SIGCHLD. Run it locally with the normal pytest command.
"""

import os
import signal
import sys

import pytest

from clippiti.__main__ import reset_child_signal_disposition

pytestmark = pytest.mark.skipif(
  os.environ.get("CI") is not None
  or os.environ.get("GITHUB_ACTIONS") is not None
  or not hasattr(signal, "SIGCHLD"),
  reason="local-only: exercises real QProcess child reaping under SIGCHLD=SIG_IGN",
)

from PyQt6.QtCore import QCoreApplication, QProcess  # noqa: E402 - after skip guard


@pytest.fixture(scope="module")
def qapp():
  # QCoreApplication is enough (no GUI / display needed) to drive QProcess.
  yield QCoreApplication.instance() or QCoreApplication(sys.argv)


@pytest.fixture(autouse=True)
def _restore_sigchld():
  previous = signal.getsignal(signal.SIGCHLD)
  try:
    yield
  finally:
    try:
      signal.signal(signal.SIGCHLD, previous)
    except (TypeError, ValueError, OSError):
      signal.signal(signal.SIGCHLD, signal.SIG_DFL)


def _run_child() -> QProcess:
  proc = QProcess()
  proc.setProgram("true")
  proc.start()
  assert proc.waitForStarted(3000), "child failed to start"
  proc.waitForFinished(3000)
  return proc


def test_sig_ign_breaks_qprocess_reaping(qapp) -> None:
  # Reproduces the bug: under SIG_IGN Qt can't reap the child and calls it a crash.
  signal.signal(signal.SIGCHLD, signal.SIG_IGN)
  proc = _run_child()
  assert proc.exitStatus() == QProcess.ExitStatus.CrashExit


def test_reset_restores_qprocess_reaping(qapp) -> None:
  # The fix: after reset, the same child is reaped and reported as a clean exit.
  signal.signal(signal.SIGCHLD, signal.SIG_IGN)
  reset_child_signal_disposition()
  proc = _run_child()
  assert proc.exitStatus() == QProcess.ExitStatus.NormalExit
  assert proc.exitCode() == 0
