"""Executable entrypoint for `clippiti`."""

import argparse
import logging
from pathlib import Path
import os
import shlex
import signal
import sys
import threading
import shutil
import importlib.util
from importlib.metadata import version, PackageNotFoundError

os.environ.setdefault('QT_QPA_ORG_NAME', 'Clippiti')
os.environ.setdefault('QT_QPA_APPLICATION_NAME', 'Clippiti')
os.environ.setdefault('QT_LOGGING_RULES', 'qt.qpa.services=false')

from .services.buffer import cleanup_orphan_session_dirs
from .services.buffer import cleanup_runtime_artifacts
from .services.buffer import SessionRuntime
from .services.buffer import start_single_session_pipeline
from .services.buffer import terminate_runtime
from .model.config import ensure_output_dirs
from .model.config import load_config
from .model.config import normalize_config
from .model.config import resolve_config_path
from .model.config import resolve_workdir
from .model.config import save_config
from .services.slsession import create_session
from .services.slsession import resolve_stream
from .services.mpvargs import build_mpv_options
from .services.clipper import ClipConfig
from .services.recording import RecordingConfig
from .ui.app import MainWindow, run_app
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget
from streamlink.exceptions import NoPluginError, StreamlinkError
from wakepy import keep as _wakepy_keep

# Determine version: prefer installed distribution metadata, fallback to package __version__
try:
  dist_ver = version('clippiti')
except PackageNotFoundError:
  import clippiti
  dist_ver = getattr(clippiti, '__version__', 'dev')


def configure_logging(verbose: bool) -> logging.Logger:
  level = logging.DEBUG if verbose else logging.INFO
  logging.basicConfig(
    level=level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
  )
  logging.getLogger("wakepy").setLevel(logging.WARNING)
  logger = logging.getLogger("clippiti")
  logger.setLevel(level)
  return logger


def reset_child_signal_disposition() -> None:
  """Restore the default SIGCHLD disposition inherited from a parent launcher.

  Launchers (e.g. lurkiti) often set SIGCHLD to SIG_IGN to auto-reap children.
  That disposition survives exec(), and under it Qt's QProcess cannot wait for
  its ffmpeg child, so clip export is wrongly reported as failed.
  """
  if not hasattr(signal, "SIGCHLD"):
    return
  try:
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
  except (ValueError, OSError):
    pass


def friendly_error_message(exc: BaseException) -> str:
  """Map an exception (unwrapping resolve_stream's RuntimeError) to a user message."""
  origin = exc.__cause__ or exc
  if isinstance(origin, NoPluginError):
    return "No Streamlink plugin found for this stream."
  if isinstance(origin, StreamlinkError):
    return f"Streamlink error: {exc}"
  return f"{exc}"


def show_error_dialog(message: str, parent: QWidget | None = None) -> None:
  # A parented (transient) dialog lets window-manager rules distinguish it from the main window.
  if parent is None:
    parent = QApplication.activeWindow()
  try:
    QMessageBox.critical(parent, "Clippiti Error", message)
  except Exception:
    logging.getLogger("clippiti").debug("failed to show error dialog", exc_info=True)


def install_excepthook() -> None:
  def excepthook(exc_type, exc_value, exc_tb):
    logging.getLogger("clippiti").critical(
      "uncaught exception", exc_info=(exc_type, exc_value, exc_tb)
    )
    message = friendly_error_message(exc_value) if exc_value is not None else f"Error: {exc_type}"
    show_error_dialog(message)

  sys.excepthook = excepthook


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    prog="clippiti",
    description="Livestream player with clipping and recording capabilities, built on Streamlink and mpv.",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=(
      "Arguments after a '--' separator are passed through to Streamlink, e.g.:\n"
      "    clippiti URL best -- --twitch-disable-ads --hls-live-edge 6\n\n"
      "To see available Streamlink options, run:\n"
      "    streamlink --help\n\n"
    ),
  )
  parser.add_argument("url", help="Stream URL to open")
  parser.add_argument(
    "quality",
    help="Desired stream quality; accepts a comma-separated fallback list, e.g. '720p,best'",
  )
  parser.add_argument(
    "--config",
    default=None,
    help="Path to config YAML file",
  )
  parser.add_argument(
    "--workdir",
    default=None,
    help="Path to runtime working directory",
  )
  parser.add_argument(
    "--verbose",
    action="store_true",
    help="Enable verbose startup logs",
  )
  parser.add_argument(
    "--mpv",
    default="",
    help="Additional mpv options (YAML or key=value pairs, e.g. 'vf=hflip' or 'hwdec: auto')",
  )
  return parser


def split_streamlink_args(argv: list[str]) -> tuple[list[str], list[str]]:
  """Split argv on the first standalone '--' separator.

  Everything before is parsed by Clippiti; everything after is forwarded to
  Streamlink's own argument parser verbatim.
  """
  if "--" in argv:
    index = argv.index("--")
    return argv[:index], argv[index + 1:]
  return list(argv), []


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
  argv = list(sys.argv[1:] if argv is None else argv)
  clippiti_argv, streamlink_argv = split_streamlink_args(argv)
  return build_parser().parse_args(clippiti_argv), streamlink_argv


def resolve_ffmpeg_path(configured: str) -> str:
  """In frozen builds, prefer an ffmpeg bundled next to the executable."""
  if configured != "ffmpeg" or not getattr(sys, "frozen", False):
    return configured
  exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
  candidates = [Path(getattr(sys, "_MEIPASS", "")) / exe_name, Path(sys.executable).parent / exe_name]
  for candidate in candidates:
    if candidate.is_file():
      return str(candidate)
  return configured


def log_startup_diagnostics(log: logging.Logger, ffmpeg_path: str) -> None:
  """Log dependency diagnostics, intended for startup failure paths only."""
  ffmpeg_bin = shutil.which(ffmpeg_path)
  if ffmpeg_bin:
    log.error("diagnostic: ffmpeg=ok (%s)", ffmpeg_bin)
  else:
    log.error("diagnostic: ffmpeg=missing (configured path=%r)", ffmpeg_path)

  has_mpv_module = importlib.util.find_spec("mpv") is not None
  if has_mpv_module:
    log.error("diagnostic: python-mpv module=ok")
  else:
    log.error("diagnostic: python-mpv module=missing")


def main(argv: list[str] | None = None) -> int:
  args, streamlink_argv = parse_args(argv)
  log = configure_logging(args.verbose)
  install_excepthook()
  reset_child_signal_disposition()
  runtime: SessionRuntime | None = None
  diagnostics_logged = False

  log.info("clippiti version %s", dist_ver)

  workdir = resolve_workdir(args.workdir)
  workdir.mkdir(parents=True, exist_ok=True)

  removed_stale = cleanup_orphan_session_dirs(workdir, current_pid=os.getpid())
  if removed_stale:
    log.info("removed stale sessions: %s", removed_stale)

  config_path = resolve_config_path(args.config, workdir)
  config = normalize_config(load_config(config_path))
  save_config(config_path, config)
  ensure_output_dirs(config)

  streamlink_default_args = str(config["streamlink"].get("default_args", ""))
  streamlink_tokens = shlex.split(streamlink_default_args) + streamlink_argv
  log.info("config: %s", config_path)
  log.info("workdir: %s", workdir)
  log.info("streamlink args: %s", " ".join(streamlink_tokens) or "(none)")

  general = config["general"]
  trigger_radius = int(general.get("controls_area", 300))
  resize_debounce_ms = int(general.get("controls_resize_debounce_ms", 40))
  ffmpeg_path = str(general.get("ffmpeg_path", "ffmpeg"))
  ffmpeg_path = resolve_ffmpeg_path(ffmpeg_path)
  segment_seconds = int(general.get("segment_seconds", 5))
  window_segments = int(general.get("window_segments", 12))

  mpv_options = build_mpv_options(
    config_options=config["general"].get("mpv_options", {}),
    cli_options_string=args.mpv,
  )
  log.info("effective mpv options: %s", mpv_options)

  startup_cancel = threading.Event()

  # Stream resolution (Streamlink plugin lookup) can be slow, notably on Twitch proxies.
  # Run it inside the background startup task so the window shows immediately.
  def startup_pipeline(report_status, report_metadata):
    report_status("Preparing Streamlink\u2026")
    session = create_session()
    report_status("Resolving stream\u2026")
    resolved = resolve_stream(
      session=session,
      url=args.url,
      quality=args.quality,
      tokens=streamlink_tokens,
    )
    metadata = resolved.metadata
    log.info(
      "metadata: plugin=%s author=%s category=%s title=%s",
      metadata.plugin,
      metadata.author,
      metadata.category,
      metadata.title,
    )
    # Update the window title/icon now; buffer startup below adds several seconds.
    report_metadata(metadata)
    return start_single_session_pipeline(
      workdir=workdir,
      ffmpeg_path=ffmpeg_path,
      url=args.url,
      quality=resolved.quality,
      stream=resolved.stream,
      segment_seconds=segment_seconds,
      window_segments=window_segments,
      metadata=metadata,
      cancel_event=startup_cancel,
      report=report_status,
    )

  def handle_startup_status(window: MainWindow, message: str) -> None:
    window.osd.show_message(message, persistent=True)

  def handle_metadata_ready(window: MainWindow, metadata_obj: object) -> None:
    metadata = metadata_obj
    window_title = (
      f"{metadata.author} - {metadata.title} - "
      f"{metadata.category} [{metadata.plugin}] - clippiti"
    )
    window.set_window_title(window_title)
    window.set_stream_icon(args.url, metadata.plugin)

  def handle_runtime_ready(window: MainWindow, ready_runtime: SessionRuntime) -> None:
    nonlocal runtime
    runtime = ready_runtime
    log.info("status: %s", runtime.status)
    log.info("playlist: %s (quality: %s)", runtime.playlist_path, runtime.desired_quality)
    log.debug("buffer_seconds: %s", runtime.buffer_seconds)
    if runtime.ffmpeg_stderr_path is not None:
      log.debug("ffmpeg_stderr: %s", runtime.ffmpeg_stderr_path)
    window.set_runtime(runtime)
    window.set_media_source(str(runtime.playlist_path))

  def handle_runtime_failure(window: MainWindow, exc: Exception) -> None:
    nonlocal diagnostics_logged
    if str(exc) == "buffer pipeline startup cancelled":
      log.debug("buffer pipeline startup cancelled")
      return
    log.error("error: startup failed (offline/private/bad args?): %s", exc)
    if not diagnostics_logged:
      diagnostics_logged = True
      log_startup_diagnostics(log, ffmpeg_path)
    show_error_dialog(friendly_error_message(exc), window)

  recording_cfg = RecordingConfig(
    output_dir=Path(str(config["recording"]["dir"])).expanduser(),
    filename_format=str(config["recording"].get("filename_format", "{author}_{timestamp}")),
    ffmpeg_path=ffmpeg_path,
    auto_remux_to_mp4=bool(config["recording"].get("auto_remux_to_mp4", False)),
  )
  clip_cfg = ClipConfig(
    output_dir=Path(str(config["clip"]["dir"])).expanduser(),
    ffmpeg_path=ffmpeg_path,
    default_duration=int(config["clip"].get("default_duration", 30)),
    filename_format=str(config["clip"].get("filename_format", "{author}.{timestamp}")),
    auto_remux_to_mp4=bool(config["clip"].get("auto_remux_to_mp4", True)),
  )

  try:
    _run_kwargs = dict(
      media_source=None,
      mpv_options=mpv_options,
      trigger_radius=trigger_radius,
      resize_debounce_ms=resize_debounce_ms,
      clip_cfg=clip_cfg,
      recording_cfg=recording_cfg,
      config=config,
      config_path=config_path,
      startup_task=startup_pipeline,
      on_startup_ready=handle_runtime_ready,
      on_startup_progress=handle_metadata_ready,
      on_startup_status=handle_startup_status,
      on_startup_failed=handle_runtime_failure,
      on_startup_cancel=startup_cancel.set,
    )
    log.debug("sleep inhibitor: activating")
    with _wakepy_keep.presenting(on_fail="warn"):
      result = run_app(**_run_kwargs)
    if runtime is None and result.startup_result is not None:
      runtime = result.startup_result
    return result.exit_code
  finally:
    startup_cancel.set()
    if runtime is not None:
      log.debug("terminate runtime begin")
      terminate_runtime(runtime)
      log.info("terminate runtime complete")
      log.debug("cleanup buffer begin (%s)", runtime.segment_dir)
      cleanup_runtime_artifacts(runtime)
      log.info("cleanup buffer complete exists=%s", runtime.segment_dir.exists())


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1:]))
