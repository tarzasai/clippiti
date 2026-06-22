"""Clip staging, preview, and export services for Clippiti."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import re
import shutil
import subprocess
import tempfile

from .buffer_engine import SessionRuntime
from .remux_queue import FfmpegJob


log = logging.getLogger("clippiti.services.clipper")

_EXTINF_RE = re.compile(r"#EXTINF:([\d.]+)")
_FFMPEG_QUIET = ["-hide_banner", "-loglevel", "error"]
_STAGE_MERGE_TIMEOUT_S = 25
_PREVIEW_TIMEOUT_S = 8


@dataclass
class ClipConfig:
  output_dir: Path
  ffmpeg_path: str = "ffmpeg"
  default_duration: int = 30


@dataclass
class ClipBufferStage:
  stage_dir: Path
  playlist_path: Path
  segments: list[tuple[Path, float]]
  total_seconds: float
  merged_ts_path: Path


@dataclass
class ClipExportContext:
  stage: ClipBufferStage
  output_path: Path


class ClipService:
  def __init__(self, config: ClipConfig) -> None:
    self._config = config

  def prepare_stage(self, runtime: SessionRuntime) -> ClipBufferStage:
    source_segments = self.parse_m3u8(runtime.playlist_path)
    if not source_segments:
      raise RuntimeError("No segments available in live playlist")

    stage_dir = Path(tempfile.mkdtemp(prefix="clippiti_clip_"))
    stage_playlist = stage_dir / "stage.m3u8"
    staged_segments: list[tuple[Path, float]] = []

    try:
      for source_path, duration in source_segments:
        if not source_path.exists():
          continue
        target_path = stage_dir / source_path.name
        shutil.copy2(source_path, target_path)
        staged_segments.append((target_path, duration))

      if not staged_segments:
        raise RuntimeError("No playable segments available for clip staging")

      self._write_playlist_entries(stage_playlist, staged_segments)
      total_seconds = sum(duration for _, duration in staged_segments)
      merged_ts_path = stage_dir / "merged.ts"

      merge_command = [
        self._config.ffmpeg_path,
        *_FFMPEG_QUIET,
        "-y",
        "-f",
        "hls",
        "-i",
        str(stage_playlist),
        "-c",
        "copy",
        str(merged_ts_path),
      ]
      subprocess.run(
        merge_command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=_STAGE_MERGE_TIMEOUT_S,
      )

      return ClipBufferStage(
        stage_dir=stage_dir,
        playlist_path=stage_playlist,
        segments=staged_segments,
        total_seconds=total_seconds,
        merged_ts_path=merged_ts_path,
      )
    except Exception:
      shutil.rmtree(stage_dir, ignore_errors=True)
      raise

  def preview_frames(self, stage: ClipBufferStage, start_seconds: float, end_seconds: float) -> tuple[Path | None, Path | None]:
    start_path = self._extract_preview_frame(stage, start_seconds, "preview_start.jpg")
    end_path = self._extract_preview_frame(stage, max(start_seconds, end_seconds - 0.1), "preview_end.jpg")
    return start_path, end_path

  def build_export_job(
    self,
    stage: ClipBufferStage,
    stream_name: str,
    start_seconds: float,
    end_seconds: float,
  ) -> FfmpegJob:
    start = max(0.0, float(start_seconds))
    end = min(float(end_seconds), stage.total_seconds)
    if end <= start:
      raise RuntimeError("Invalid clip range")

    selected = self.select_range_segments(stage.segments, start, end)
    if not selected:
      raise RuntimeError("No segments available for the requested clip range")

    output_path = self._build_output_path(stream_name)
    clip_seconds = end - start

    return FfmpegJob(
      target_path=output_path,
      ffmpeg_path=self._config.ffmpeg_path,
      arguments=[
        *_FFMPEG_QUIET,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(stage.merged_ts_path),
        "-c",
        "copy",
        "-t",
        f"{clip_seconds:.3f}",
        str(output_path),
      ],
      stderr_path=self._stderr_log_path(output_path),
      kind="clip",
      context=ClipExportContext(stage=stage, output_path=output_path),
    )

  def cleanup(self, stage: ClipBufferStage) -> None:
    shutil.rmtree(stage.stage_dir, ignore_errors=True)

  @staticmethod
  def parse_m3u8(playlist_path: Path) -> list[tuple[Path, float]]:
    segments: list[tuple[Path, float]] = []
    duration: float | None = None
    base_dir = playlist_path.parent
    with playlist_path.open(encoding="utf-8") as handle:
      for raw_line in handle:
        line = raw_line.strip()
        match = _EXTINF_RE.match(line)
        if match:
          duration = float(match.group(1))
          continue
        if line and not line.startswith("#"):
          seg_path = Path(line) if Path(line).is_absolute() else base_dir / line
          segments.append((seg_path, duration or 0.0))
          duration = None
    return segments

  @staticmethod
  def select_range_segments(
    segments: list[tuple[Path, float]],
    start_seconds: float,
    end_seconds: float,
  ) -> list[tuple[Path, float]]:
    if end_seconds <= start_seconds:
      return []

    selected: list[tuple[Path, float]] = []
    cursor = 0.0
    for seg_path, duration in segments:
      seg_start = cursor
      seg_end = cursor + duration
      cursor = seg_end
      if seg_end <= start_seconds:
        continue
      if seg_start >= end_seconds:
        break
      selected.append((seg_path, duration))
    return selected

  def _extract_preview_frame(self, stage: ClipBufferStage, at_seconds: float, output_name: str) -> Path | None:
    output_path = stage.stage_dir / output_name
    safe_at = max(0.0, min(at_seconds, max(0.0, stage.total_seconds - 0.1)))
    command = [
      self._config.ffmpeg_path,
      "-y",
      *_FFMPEG_QUIET,
      "-ss",
      f"{safe_at:.3f}",
      "-i",
      str(stage.merged_ts_path),
      "-frames:v",
      "1",
      "-q:v",
      "2",
      str(output_path),
    ]
    try:
      subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=_PREVIEW_TIMEOUT_S,
      )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
      fallback = [
        self._config.ffmpeg_path,
        "-y",
        *_FFMPEG_QUIET,
        "-i",
        str(stage.merged_ts_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
      ]
      try:
        subprocess.run(
          fallback,
          check=True,
          stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL,
          timeout=_PREVIEW_TIMEOUT_S,
        )
      except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return output_path

  def _build_output_path(self, stream_name: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^\w\-.]", "_", stream_name)
    output_dir = self._config.output_dir.expanduser() / safe_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{safe_name}_{ts}.mp4"

  @staticmethod
  def _write_playlist_entries(playlist_path: Path, segments: list[tuple[Path, float]]) -> None:
    target_duration = max(1, int(max((duration for _, duration in segments), default=1.0) + 0.999))
    lines = [
      "#EXTM3U",
      "#EXT-X-VERSION:3",
      f"#EXT-X-TARGETDURATION:{target_duration}",
      "#EXT-X-MEDIA-SEQUENCE:0",
    ]
    for seg_path, duration in segments:
      lines.append(f"#EXTINF:{duration:.6f},")
      lines.append(seg_path.name)
    lines.append("#EXT-X-ENDLIST")
    playlist_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

  @staticmethod
  def _stderr_log_path(output_path: Path) -> Path | None:
    if not log.isEnabledFor(logging.DEBUG):
      return None
    return output_path.with_suffix(".stderr.log")
