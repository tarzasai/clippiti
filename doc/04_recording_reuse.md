# Recording Reuse Specification

## Objective
Preserve StreamKeeper recording reliability in a single-session app.

## Source behavior to preserve
From `recorder.py`:
- recording output naming and directory creation
- ffmpeg command reading from live playlist
- recorder process lifecycle
- optional remux from `.ts` to `.mp4` on stop
- defensive checks for terminated upstream processes

## Recording flow in Clippiti
1. User clicks Record.
2. Validate session pipeline is alive and playlist exists.
3. Start ffmpeg recorder process against current `live.m3u8`.
4. Update UI state to recording.
5. On stop, terminate recorder gracefully.
6. If remux enabled, copy-remux to mp4 and remove ts on success.

## Recommended command behavior
- keep `-c copy`
- keep low-latency source via local HLS playlist
- keep stderr capture for remux diagnostics

## Single-session API proposal

```python
class RecordingService:
    def start(runtime: SessionRuntime, cfg: RecordingConfig) -> RecordingStartResult: ...
    def stop(runtime: SessionRuntime, cfg: RecordingConfig) -> RecordingStopResult: ...
    def is_recording(runtime: SessionRuntime) -> bool: ...
```

## UI behavior
- Record button toggles between:
  - `Start Recording`
  - `Stop Recording`
- During recording:
  - show elapsed timer (optional)
  - disable actions that invalidate runtime state
- On stop:
  - show saved filename and remux status

## Failure handling
- if streamlink/segmenter exits, auto-stop recording and notify user
- if remux fails, keep `.ts` and clearly report fallback

## Suggested defaults for independent app
- recording directory: `~/Videos/Clippiti/recordings`
- filename format: `{name}_{timestamp}`
- remux default: off (safer) or on (user preference)
