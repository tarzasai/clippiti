# Clippiti Player: Reuse Master Plan

## Goal
Build a brand new, fully independent application named **Clippiti Player** that:
- launches for one stream URL (+ streamlink arguments)
- starts a rolling buffer immediately
- plays the live stream in-app via python-mpv
- supports clipping from buffer
- supports recording from live playlist
- allows multiple app instances (one per stream)

This document maps exactly what to reuse from StreamKeeper and what to exclude.

## High-level extraction strategy
1. Reuse backend logic for buffer, clip, and record.
2. Remove multi-stream manager concepts and convert to single-session runtime.
3. Replace external player launch with embedded python-mpv widget.
4. Keep clip dialog UX and ffmpeg export behavior.
5. Remove all SC integration, webcast, and centralized app registry logic.

## Reuse decision summary

### Reuse with minor adaptation
- `src/streamkeeper/services/sl_helper.py`
- `src/streamkeeper/services/process_manager.py`
- `src/streamkeeper/services/clipper.py`
- `src/streamkeeper/services/recorder.py`
- `src/streamkeeper/ui/clip_dialog.py`
- parts of `src/streamkeeper/services/streams_controller.py` related to clip/record readiness and lifecycle
- `src/streamkeeper/model/runtime.py`

### Reuse only patterns, not structure
- `src/streamkeeper/model/config.py` (shrink to single-session schema)
- `src/streamkeeper/app.py` (app skeleton only)

### Do not reuse
- `src/streamkeeper/services/webcast_server.py`
- `src/streamkeeper/services/sc_sync.py`
- `src/streamkeeper/services/sc_watcher.py`
- most of `src/streamkeeper/ui/streams_tab.py`
- StreamCondor-specific config and filters
- multi-row stream table, activation limits, grouped list UI

## New single-session mental model
- One process = one stream session.
- Session owns:
  - stream metadata
  - streamlink process
  - ffmpeg segmenter process
  - local rolling HLS playlist/segments
  - optional active recorder process
  - clip staging temp data
- Window controls session directly:
  - Play/Pause (mpv)
  - Volume slider (mpv)
  - Clip button (opens clip dialog)
  - Record toggle button
  - Snapshot button (save current frame as image)
- Player should fill the app window, with controls floating over the video in a compact corner panel.
- The overlay panel should support moving to another corner and switching between horizontal and vertical control layouts.

## Why this architecture is correct
- Keeps all proven data-plane behavior (buffer, clip, record).
- Removes complexity that came from managing many streams in one process.
- Fits python-mpv strengths for continuous live playback.
- Maintains isolated state so multiple instances are naturally supported.

## Independence constraints
Clippiti Player must not depend on:
- StreamKeeper config files
- StreamCondor files or watcher paths
- StreamKeeper runtime folders
- StreamKeeper package imports at runtime

Use copied modules (renamed/repackaged) under the new project namespace.

## Deliverables expected in Clippiti project
- single executable entrypoint (`clippiti`) for distribution `clippiti-player`
- session runtime package
- clip dialog package
- mpv embedding adapter
- independent config schema and default paths
- automated tests for buffer, clip, and record flows
