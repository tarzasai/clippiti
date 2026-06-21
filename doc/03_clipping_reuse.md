# Clipping Reuse Specification

## Objective
Keep clipping quality and speed behavior from StreamKeeper while decoupling from multi-stream architecture.

## Source logic to preserve
From `clipper.py`:
- parse m3u8 durations (`#EXTINF`)
- select segments by range or tail
- stage buffer copy into temp directory
- optional merge of staged segments to one TS (`merged.ts`)
- clip export via ffmpeg copy path
- preview frame extraction
- cleanup helpers

From `clip_dialog.py`:
- custom range slider
- selected duration labels
- start/end preview frame panes
- second tick marks
- exact selection display with optional hidden export margins

## Clipping flow in Clippiti
1. User clicks Clip.
2. App snapshots current session buffer into stage directory.
3. App opens clip dialog.
4. Dialog loads preview frames for selected range (with optional margins for preview/export).
5. User confirms.
6. App exports mp4 clip from stage snapshot.
7. App cleans stage folder.

## Why snapshot staging stays essential
- avoids race conditions while live buffer keeps changing
- ensures preview and export reference the same static segment set
- improves user trust: output matches dialog preview

## Config knobs to carry over
- clip output directory
- max clip duration
- default duration
- optional margin seconds before/after selection (if enabled)

## Suggested Clippiti clip service contract

```python
class ClipService:
    def prepare_stage(runtime: SessionRuntime) -> ClipStage: ...
    def preview_frames(stage: ClipStage, start_s: float, end_s: float) -> tuple[Path, Path]: ...
    def export(stage: ClipStage, stream_name: str, start_s: float, end_s: float) -> ClipResult: ...
    def cleanup(stage: ClipStage) -> None: ...
```

## UI notes
- Keep current dialog almost unchanged.
- Replace references to controller global stream map with session-scoped callbacks.
- Keep range slider features:
  - min duration
  - second ticks
  - start/end labels
  - duration label

## Performance notes
- keep ffmpeg quiet flags for UX cleanliness
- keep `-c copy` export path where possible for speed
- continue to use merged TS for faster seek behavior during preview/export
