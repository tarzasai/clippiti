# Function-Level Transplant Map

This file is a direct, code-granularity checklist for migration from StreamKeeper to Clippiti Player.

## A) Streamlink helper transplant
Source: `src/streamkeeper/services/sl_helper.py`

Keep (copy with namespace updates):
- `build_streamlink_command`
- `_resolve_placeholders`
- `_split_args_with_values`
- `_parse_args_string`
- `_merge_args_strings`
- `StreamlinkOutputState`
- `apply_streamlink_output_line`
- `StreamMetadata` — adapt to hold `plugin`, `author`, `category`, `title` from the `streamlink --json` response shape:
  ```json
  {
    "plugin": "...",
    "metadata": { "author": "...", "category": "...", "title": "..." }
  }
  ```
- `resolve_stream_metadata`

Adjust:
- import paths for config/session models
- timeout and error messages to new app naming

---

## B) Runtime model transplant
Source: `src/streamkeeper/model/runtime.py`

Keep:
- `BinaryLineBuffer`
- `ManagedStream` structure as base

Rename and adjust:
- `ManagedStream` -> `SessionRuntime`
- keep fields:
  - `url`, `label`, `desired_quality`
  - `stream_title`, `stream_author`, `stream_category`, `actual_quality`
  - `segment_dir`, `playlist_path`
  - `streamlink_proc`, `ffmpeg_seg_proc`, `recorder_proc`
  - `streamlink_stderr`, `streamlink_stderr_buffer`
  - recording output/remux fields
- drop fields strictly related to multi-stream registry if not needed

---

## C) Process pipeline transplant
Source: `src/streamkeeper/services/process_manager.py`

Keep:
- `SubprocessLauncher.start_pipeline`
- `SubprocessLauncher.terminate`
- `SubprocessLauncher.wait`
- ffmpeg segmenter command builder internals
- non-blocking stderr setup
- process teardown order

Rewrite:
- `activate_stream` -> `start_session`
- `deactivate_stream` -> `stop_session`
- remove:
  - `_active` map
  - activation limit constraints
  - stream-id lookup APIs

---

## D) Orchestrator logic transplant
Source: `src/streamkeeper/services/runtime_orchestrator.py`

Keep as pattern:
- metadata resolution as the first action on session start (before pipeline launch)
  - failure = stream offline or private; abort session with user-visible error
- periodic streamlink stderr poll
- quality update propagation
- terminated pipeline detection

Drop:
- URL <-> stream_id map and all map APIs
- webcast registration calls

Replace with:
- single `SessionCoordinator` owning one runtime instance

---

## E) Clip services transplant
Source: `src/streamkeeper/services/clipper.py`

Keep nearly as-is:
- `_EXTINF_RE`, `_FFMPEG_QUIET`
- `parse_m3u8`
- `select_tail_segments`
- `build_clip_output_path`
- `build_clip_ffmpeg_command`
- `ClipResult`
- `ClipBufferStage`
- `_write_playlist_entries`
- `select_range_segments`
- `stage_clip_buffer`
- `extract_preview_frame` (if present below loaded range)
- `create_clip_from_stage` (if present below loaded range)
- `cleanup_clip_stage` (if present below loaded range)

Adjust:
- default directories to Clippiti paths
- stream naming/sanitization policy if needed

---

## F) Clip controller functions transplant
Source: `src/streamkeeper/services/streams_controller.py`

Keep logic (session-scoped rewrite):
- `_playlist_has_segment`
- `_playlist_buffer_seconds`
- `_prepare_clip_runtime`
- `prepare_clip_stage`
- `clip_stage_preview_frames`
- `clip_from_stage`
- `cleanup_clip_stage`

Rewrite:
- remove stream URL argument in favor of current session runtime

---

## G) Clip dialog transplant
Source: `src/streamkeeper/ui/clip_dialog.py`

Keep:
- `_RangeSlider`
- `ClipRangeDialog` layout and behavior
- tick marks, preview labels, range methods

Optional edit:
- remove internal `QMediaPlayer/QVideoWidget` from clip dialog if Clippiti wants only frame previews there
- or keep as optional dialog video preview mode

---

## H) Recorder transplant
Source: `src/streamkeeper/services/recorder.py`

Keep nearly as-is:
- dataclasses (`RecordingStartResult`, `RecordingStopResult`)
- `build_recording_output_path`
- `build_recording_ffmpeg_command`
- `build_remux_command`
- `_terminated_process_reason`
- `start_recording`
- `stop_recording`

Adjust:
- model imports (`RecordingConfig`, runtime class)
- output directory defaults

---

## I) Recording controller functions transplant
Source: `src/streamkeeper/services/streams_controller.py`

Keep logic (session-scoped rewrite):
- `is_recording`
- `start_recording`
- `stop_recording`

Remove:
- stream URL map resolution
- batch stop methods for all streams

---

## J) Config model transplant
Source: `src/streamkeeper/model/config.py`

Keep concepts:
- streamlink defaults
- clip config
- recording config
- player defaults

Drop:
- streams dictionary for many streams
- webcast config
- StreamCondor integration config
- UI table column configs

---

## K) UI transplant summary
Source: `src/streamkeeper/ui/streams_tab.py`

Do not transplant directly.

Only keep ideas:
- toolbar actions and status updates
- file-system watcher approach for buffer-ready toggles

New UI for Clippiti should be a single player window, not a stream table.
