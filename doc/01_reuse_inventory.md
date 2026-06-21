# Reuse Inventory (Source -> Clippiti)

## Source files to extract

## 1) Streamlink command and metadata helpers
Source:
- `src/streamkeeper/services/sl_helper.py`

Reuse:
- `build_streamlink_command`
- placeholder resolution and argument merging helpers
- streamlink output quality parsing state logic
- metadata resolution (`streamlink --json`), extracting `plugin`, `metadata.author`, `metadata.category`, `metadata.title`

Changes required:
- remove references to StreamKeeper-specific model classes
- move to plain dataclasses or Clippiti session models
- keep command-generation behavior exactly (quality fallback included)

---

## 2) Runtime state model
Source:
- `src/streamkeeper/model/runtime.py`

Reuse:
- `ManagedStream` concept (rename to `SessionRuntime`)
- `BinaryLineBuffer`

Changes required:
- drop fields not needed for multi-stream table grouping
- keep process handles and buffer paths
- preserve stream metadata fields (title/author/category)

---

## 3) Process and buffer pipeline
Source:
- `src/streamkeeper/services/process_manager.py`

Reuse:
- pipeline startup sequence:
  - streamlink stdout -> ffmpeg segmenter stdin
- ffmpeg HLS segmenter options:
  - `-hls_time`
  - `-hls_list_size`
  - `-hls_flags delete_segments+append_list+temp_file`
  - segment filename template
- stderr non-blocking read setup for streamlink

Changes required:
- remove activation limit and stream map management
- convert manager API from multi-stream to single session lifecycle
- keep launcher abstraction if testability is desired

---

## 4) Clip subsystem
Source:
- `src/streamkeeper/services/clipper.py`
- clip-related methods in `src/streamkeeper/services/streams_controller.py`
- `src/streamkeeper/ui/clip_dialog.py`

Reuse:
- playlist parsing and range segment selection
- stage buffer snapshots and merged TS generation
- frame extraction for start/end previews
- ffmpeg clip export commands and output naming
- UI slider + labels + frame previews in clip dialog

Changes required:
- replace Qt preview player in clip dialog if desired (optional)
- keep current behavior where user selection is exact and export may apply margins
- bind dialog callbacks to Clippiti session controller

---

## 5) Recording subsystem
Source:
- `src/streamkeeper/services/recorder.py`
- recording methods in `src/streamkeeper/services/streams_controller.py`

Reuse:
- recording ffmpeg command from live playlist
- stop/terminate + optional remux flow
- output path naming rules

Changes required:
- remove references to StreamKeeper `RecordingConfig` and adapt to Clippiti config
- expose simple `start_recording()` and `stop_recording()` on session controller

---

## 6) Controller patterns
Source:
- `src/streamkeeper/services/streams_controller.py`
- `src/streamkeeper/services/runtime_orchestrator.py`

Reuse as pattern:
- readiness checks (`_playlist_has_segment`, playlist buffer seconds)
- defensive process-termination checks before clip/record
- poll loop for streamlink quality updates

Do not copy directly:
- URL->ID maps
- bulk deactivate for many streams
- webcast URL helper functions
- SC auto-activation features
