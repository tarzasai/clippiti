"""Executable entrypoint for `clippiti`."""

import argparse
import logging
from pathlib import Path
import os
import sys
import threading
import shutil
import importlib.util
from importlib.metadata import version, PackageNotFoundError
from typing import TYPE_CHECKING

os.environ.setdefault('QT_QPA_ORG_NAME', 'Clippiti')
os.environ.setdefault('QT_QPA_APPLICATION_NAME', 'Clippiti')
os.environ.setdefault('QT_LOGGING_RULES', 'qt.qpa.services=false')

from .services.buffer_engine import cleanup_orphan_session_dirs
from .services.buffer_engine import resolve_stream_metadata
from .services.buffer_engine import cleanup_runtime_artifacts
from .services.buffer_engine import start_single_session_pipeline
from .services.buffer_engine import terminate_runtime
from .model.config import ensure_output_dirs
from .model.config import load_config
from .model.config import normalize_config
from .model.config import resolve_config_path
from .model.config import resolve_workdir
from .model.config import save_config
from .services.streamlink_args import build_streamlink_command
from .services.mpv_args import build_mpv_options
from .services.clipper import ClipConfig
from .services.recording import RecordingConfig
from .ui.app import run_app
from wakepy import keep as _wakepy_keep

if TYPE_CHECKING:
  from .services.buffer_engine import SessionRuntime
  from .ui.app import MainWindow

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


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    prog="clippiti",
    description="Single-stream live player with floating controls.",
  )
  parser.add_argument("url", help="Stream URL to open")
  parser.add_argument("quality", help="Desired stream quality (for streamlink pipeline)")
  parser.add_argument(
    "--sl",
    default="",
    help="Pass-through Streamlink arguments string",
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
  return build_parser().parse_args(argv)


def log_startup_diagnostics(log: logging.Logger, ffmpeg_path: str) -> None:
  """Log dependency diagnostics, intended for startup failure paths only."""
  streamlink_bin = shutil.which("streamlink")
  if streamlink_bin:
    log.error("diagnostic: streamlink=ok (%s)", streamlink_bin)
  else:
    log.error("diagnostic: streamlink=missing (not found in PATH)")

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
  args = parse_args(argv)
  log = configure_logging(args.verbose)
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
  streamlink_cmd = build_streamlink_command(
    url=args.url,
    quality=args.quality,
    default_args=streamlink_default_args,
    cli_args=args.sl,
  )
  log.info("config: %s", config_path)
  log.info("workdir: %s", workdir)
  log.info("streamlink argv: %s", " ".join(streamlink_cmd))

  general = config["general"]
  trigger_radius = int(general.get("controls_area", 300))
  resize_debounce_ms = int(general.get("controls_resize_debounce_ms", 40))
  ffmpeg_path = str(general.get("ffmpeg_path", "ffmpeg"))
  segment_seconds = int(general.get("segment_seconds", 5))
  window_segments = int(general.get("window_segments", 12))

  mpv_options = build_mpv_options(
    config_options=config["general"].get("mpv_options", {}),
    cli_options_string=args.mpv,
  )
  log.info("effective mpv options: %s", mpv_options)

  try:
    metadata = resolve_stream_metadata(
      url=args.url,
      default_args=streamlink_default_args,
      cli_args=args.sl,
    )
  except Exception as exc:
    log.error("error: stream metadata probe failed (offline/private?): %s", exc)
    if not diagnostics_logged:
      diagnostics_logged = True
      log_startup_diagnostics(log, ffmpeg_path)
    return 2

  log.info(
    "metadata: plugin=%s author=%s category=%s title=%s",
    metadata.plugin,
    metadata.author,
    metadata.category,
    metadata.title,
  )

  window_title = f"{metadata.author} - {metadata.title} - {metadata.category} [{metadata.plugin}] - clippiti"

  startup_cancel = threading.Event()

  def startup_pipeline():
    return start_single_session_pipeline(
      workdir=workdir,
      ffmpeg_path=ffmpeg_path,
      url=args.url,
      quality=args.quality,
      streamlink_cmd=streamlink_cmd,
      segment_seconds=segment_seconds,
      window_segments=window_segments,
      metadata=metadata,
      cancel_event=startup_cancel,
    )

  def handle_runtime_ready(window: MainWindow, ready_runtime: SessionRuntime) -> None:
    nonlocal runtime
    runtime = ready_runtime
    log.info("status: %s", runtime.status)
    log.info("playlist: %s", runtime.playlist_path)
    log.debug("buffer_seconds: %s", runtime.buffer_seconds)
    if runtime.streamlink_stderr_path is not None:
      log.debug("streamlink_stderr: %s", runtime.streamlink_stderr_path)
    if runtime.ffmpeg_stderr_path is not None:
      log.debug("ffmpeg_stderr: %s", runtime.ffmpeg_stderr_path)
    window.set_runtime(runtime)
    window.set_media_source(str(runtime.playlist_path))

  def handle_runtime_failure(exc: Exception) -> None:
    nonlocal diagnostics_logged
    if str(exc) == "buffer pipeline startup cancelled":
      log.debug("buffer pipeline startup cancelled")
      return
    log.error("error: failed to start buffer pipeline: %s", exc)
    if not diagnostics_logged:
      diagnostics_logged = True
      log_startup_diagnostics(log, ffmpeg_path)

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
  )

  try:
    _run_kwargs = dict(
      media_source=None,
      mpv_options=mpv_options,
      trigger_radius=trigger_radius,
      resize_debounce_ms=resize_debounce_ms,
      window_title=window_title,
      clip_cfg=clip_cfg,
      recording_cfg=recording_cfg,
      config=config,
      config_path=config_path,
      startup_task=startup_pipeline,
      on_startup_ready=handle_runtime_ready,
      on_startup_failed=handle_runtime_failure,
      on_startup_cancel=startup_cancel.set,
    )
    log.debug("sleep inhibitor: activating")
    with _wakepy_keep.running(on_fail="warn"):
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
