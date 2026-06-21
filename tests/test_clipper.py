from pathlib import Path
import subprocess

from clippiti.services.buffer_engine import SessionRuntime
from clippiti.services.clipper import ClipService


def test_parse_m3u8_reads_relative_segments(tmp_path: Path) -> None:
  playlist = tmp_path / "live.m3u8"
  playlist.write_text(
    "\n".join(
      [
        "#EXTM3U",
        "#EXTINF:2.000,",
        "seg_00001.ts",
        "#EXTINF:3.500,",
        "seg_00002.ts",
      ]
    )
    + "\n",
    encoding="utf-8",
  )

  parsed = ClipService.parse_m3u8(playlist)

  assert parsed == [
    (tmp_path / "seg_00001.ts", 2.0),
    (tmp_path / "seg_00002.ts", 3.5),
  ]


def test_select_range_segments_overlapping_only() -> None:
  segments = [
    (Path("seg1.ts"), 2.0),
    (Path("seg2.ts"), 2.0),
    (Path("seg3.ts"), 2.0),
  ]

  selected = ClipService.select_range_segments(segments, start_seconds=1.0, end_seconds=4.1)

  assert selected == [
    (Path("seg1.ts"), 2.0),
    (Path("seg2.ts"), 2.0),
    (Path("seg3.ts"), 2.0),
  ]


def test_select_range_segments_empty_when_invalid() -> None:
  segments = [(Path("seg1.ts"), 2.0)]

  assert ClipService.select_range_segments(segments, 3.0, 3.0) == []
  assert ClipService.select_range_segments(segments, 4.0, 1.0) == []


def _runtime_for_clipper(tmp_path: Path) -> SessionRuntime:
  return SessionRuntime(
    url="https://example.com/live",
    desired_quality="best",
    stream_title="Title",
    stream_author="Author",
    stream_category="Category",
    plugin="plugin",
    segment_dir=tmp_path,
    playlist_path=tmp_path / "live.m3u8",
    segment_seconds=5,
    window_segments=12,
  )


def test_prepare_stage_success(tmp_path: Path, monkeypatch) -> None:
  runtime = _runtime_for_clipper(tmp_path)
  seg1 = tmp_path / "seg1.ts"
  seg2 = tmp_path / "seg2.ts"
  seg1.write_text("a", encoding="utf-8")
  seg2.write_text("b", encoding="utf-8")
  runtime.playlist_path.write_text(
    "#EXTM3U\n#EXTINF:2.0,\nseg1.ts\n#EXTINF:3.0,\nseg2.ts\n",
    encoding="utf-8",
  )

  stage_dir = tmp_path / "stage"
  def fake_mkdtemp(**kwargs):
    stage_dir.mkdir(parents=True, exist_ok=True)
    return str(stage_dir)

  monkeypatch.setattr("clippiti.services.clipper.tempfile.mkdtemp", fake_mkdtemp)

  def fake_run(cmd, **kwargs):
    Path(cmd[-1]).write_text("merged", encoding="utf-8")
    return None

  monkeypatch.setattr("clippiti.services.clipper.subprocess.run", fake_run)

  service = ClipService(ClipConfig(output_dir=tmp_path, ffmpeg_path="ffmpeg"))
  stage = service.prepare_stage(runtime)

  assert stage.stage_dir == stage_dir
  assert stage.playlist_path.exists()
  assert stage.merged_ts_path.exists()
  assert stage.total_seconds == 5.0


def test_prepare_stage_no_segments_raises(tmp_path: Path) -> None:
  runtime = _runtime_for_clipper(tmp_path)
  runtime.playlist_path.write_text("#EXTM3U\n", encoding="utf-8")
  service = ClipService(ClipConfig(output_dir=tmp_path))

  try:
    service.prepare_stage(runtime)
    assert False
  except RuntimeError as exc:
    assert "No segments" in str(exc)


def test_prepare_stage_cleanup_on_merge_failure(tmp_path: Path, monkeypatch) -> None:
  runtime = _runtime_for_clipper(tmp_path)
  (tmp_path / "seg1.ts").write_text("a", encoding="utf-8")
  runtime.playlist_path.write_text("#EXTM3U\n#EXTINF:2.0,\nseg1.ts\n", encoding="utf-8")
  stage_dir = tmp_path / "stage_fail"
  def fake_mkdtemp(**kwargs):
    stage_dir.mkdir(parents=True, exist_ok=True)
    return str(stage_dir)

  monkeypatch.setattr("clippiti.services.clipper.tempfile.mkdtemp", fake_mkdtemp)

  def bad_run(*args, **kwargs):
    raise subprocess.CalledProcessError(1, "ffmpeg")

  monkeypatch.setattr("clippiti.services.clipper.subprocess.run", bad_run)

  service = ClipService(ClipConfig(output_dir=tmp_path))
  try:
    service.prepare_stage(runtime)
    assert False
  except subprocess.CalledProcessError:
    assert not stage_dir.exists()

from clippiti.services.clipper import ClipBufferStage
from clippiti.services.clipper import ClipConfig
from clippiti.services.clipper import ClipService


def test_build_output_path_sanitizes_stream_name(tmp_path: Path) -> None:
  service = ClipService(ClipConfig(output_dir=tmp_path))
  out = service._build_output_path("Bad:/Name")
  assert out.suffix == ".mp4"
  assert "Bad__Name" in str(out)


def test_build_export_job_rejects_invalid_range(tmp_path: Path) -> None:
  service = ClipService(ClipConfig(output_dir=tmp_path))
  stage = ClipBufferStage(
    stage_dir=tmp_path,
    playlist_path=tmp_path / "stage.m3u8",
    segments=[(tmp_path / "seg.ts", 2.0)],
    total_seconds=2.0,
    merged_ts_path=tmp_path / "merged.ts",
  )
  try:
    service.build_export_job(stage, "name", 1.0, 0.5)
    assert False
  except RuntimeError as exc:
    assert "Invalid clip range" in str(exc)


def test_build_export_job_creates_job(tmp_path: Path) -> None:
  service = ClipService(ClipConfig(output_dir=tmp_path, ffmpeg_path="ffmpeg"))
  stage = ClipBufferStage(
    stage_dir=tmp_path,
    playlist_path=tmp_path / "stage.m3u8",
    segments=[(tmp_path / "seg.ts", 5.0)],
    total_seconds=5.0,
    merged_ts_path=tmp_path / "merged.ts",
  )
  job = service.build_export_job(stage, "name", 0.5, 3.0)

  assert job.ffmpeg_path == "ffmpeg"
  assert job.kind == "clip"
  assert job.target_path.suffix == ".mp4"


def test_write_playlist_entries(tmp_path: Path) -> None:
  playlist = tmp_path / "stage.m3u8"
  segments = [(tmp_path / "a.ts", 1.2), (tmp_path / "b.ts", 2.0)]
  ClipService._write_playlist_entries(playlist, segments)
  text = playlist.read_text(encoding="utf-8")
  assert "#EXTM3U" in text
  assert "#EXT-X-ENDLIST" in text


def test_extract_preview_frame_fallback(monkeypatch, tmp_path: Path) -> None:
  service = ClipService(ClipConfig(output_dir=tmp_path, ffmpeg_path="ffmpeg"))
  stage = ClipBufferStage(
    stage_dir=tmp_path,
    playlist_path=tmp_path / "stage.m3u8",
    segments=[],
    total_seconds=3.0,
    merged_ts_path=tmp_path / "merged.ts",
  )

  calls = {"count": 0}

  def fake_run(*args, **kwargs):
    calls["count"] += 1
    if calls["count"] == 1:
      raise service.__class__.__mro__[0].__module__ and __import__("subprocess").CalledProcessError(1, "ffmpeg")
    return None

  monkeypatch.setattr("clippiti.services.clipper.subprocess.run", fake_run)
  out = service._extract_preview_frame(stage, 1.0, "x.jpg")
  assert out is not None


def test_extract_preview_frame_double_failure(monkeypatch, tmp_path: Path) -> None:
  service = ClipService(ClipConfig(output_dir=tmp_path, ffmpeg_path="ffmpeg"))
  stage = ClipBufferStage(
    stage_dir=tmp_path,
    playlist_path=tmp_path / "stage.m3u8",
    segments=[],
    total_seconds=3.0,
    merged_ts_path=tmp_path / "merged.ts",
  )

  def fail_run(*args, **kwargs):
    raise subprocess.CalledProcessError(1, "ffmpeg")

  monkeypatch.setattr("clippiti.services.clipper.subprocess.run", fail_run)
  assert service._extract_preview_frame(stage, 1.0, "x.jpg") is None


def test_stderr_log_path_respects_debug(monkeypatch, tmp_path: Path) -> None:
  service = ClipService(ClipConfig(output_dir=tmp_path))
  monkeypatch.setattr("clippiti.services.clipper.log.isEnabledFor", lambda *_: False)
  assert service._stderr_log_path(tmp_path / "x.mp4") is None


def test_cleanup_removes_stage_dir(tmp_path: Path) -> None:
  service = ClipService(ClipConfig(output_dir=tmp_path))
  stage_dir = tmp_path / "stage"
  stage_dir.mkdir()
  stage = ClipBufferStage(
    stage_dir=stage_dir,
    playlist_path=stage_dir / "stage.m3u8",
    segments=[],
    total_seconds=0.0,
    merged_ts_path=stage_dir / "merged.ts",
  )
  service.cleanup(stage)
  assert not stage_dir.exists()
