# Implementation Sequence and Acceptance Criteria

## Deliverable 1: App Shell (first shippable milestone)
- Implement full CLI interface per spec in [doc/07_cli_and_config_spec.md](doc/07_cli_and_config_spec.md):
  - positional `url`, `quality`
  - optional `--sl`, `--config`, `--workdir`, `--verbose`
- Implement configuration model and lifecycle:
  - schema-backed config model
  - default values
  - load from file
  - save/write back to file
- Implement a functional main window shell with embedded player surface and moving control panel:
  - moving panel behavior is fully working (corner/orientation movement rules)
  - panel interaction/animation behavior is working
  - panel buttons are placeholders (no clip/record/settings actions yet)
  - snapshot/clip/record business actions are intentionally out of scope for this milestone

Acceptance:
- `clippiti --help` shows the full CLI contract from doc 07
- app accepts CLI arguments and resolves config + defaults deterministically
- `--sl` supports multi-argument Streamlink pass-through (shell-style tokenization) and merges with `streamlink.default_args` in deterministic order
- app can load an existing config and save updates to disk
- `general.mpv_options` applies only allowlisted keys, while render-API-critical options remain app-forced
- main window opens with working floating panel movement behavior (corner/orientation states cycle via Ctrl+Click move button)
- volume indicator (mute button) always visible when panel is collapsed; icon updates based on volume level (muted/low/medium/high)
- volume can be adjusted via mouse wheel (±5% on scroll) or keyboard when window focused: `-`, `+`, `PgDn`, `PgUp` keys
- volume adjustment displays visual feedback (white gradient overlay on video, similar to mpv)
- mute toggle button preserves stored volume level
- button clicks do not crash the app even when actions are not implemented
- no StreamKeeper/SC imports exist

## Deliverable 2: Buffer engine
- Port streamlink command builder + metadata resolver.
- Run `streamlink --json` as the first action on launch to fetch stream metadata.
- If the metadata call fails, surface an error (stream offline or private) and abort — do not start the buffer pipeline.
- Port process manager pipeline startup for single session.
- Expose playlist path and buffer-seconds calculation.

Acceptance:
- launching against an offline/private URL shows an error and exits cleanly
- `live.m3u8` appears and rolls for a live URL
- segment files rotate by configured window
- status reflects loading -> live

## Deliverable 3: python-mpv embedding
- Add player adapter and widget integration.
- Open session playlist in embedded player.
- Add play/pause + volume controls.
- Add the floating corner control panel with corner relocation and horizontal/vertical layout toggles.
- Add snapshot capture from the current frame and wire it to the configured snapshot directory.

Acceptance:
- stream plays in-window
- volume slider works
- playback recovers from short transient interruption
- snapshot saves the current frame as an image

## Deliverable 4: clipping
- Port clipper service and clip stage flow.
- Port clip dialog and connect callbacks.
- Preserve preview + export behavior.

Acceptance:
- user can clip selected range from active buffer
- output file plays correctly
- preview frames reflect exported clip boundaries

## Deliverable 5: recording
- Port recorder service.
- Add record toggle in main window.
- Add optional remux behavior.

Acceptance:
- recording starts/stops reliably
- output ts/mp4 files are valid and complete

## Deliverable 6: robustness and packaging
- add structured logging
- add startup diagnostics (ffmpeg/mpv/streamlink availability)
- package executable (`clippiti`) for distribution `clippiti-player`

Acceptance:
- multiple app instances can run simultaneously on different streams
- each instance cleans only its own runtime folder
- no cross-instance collisions

## Core test matrix

### Unit tests
- streamlink command building
- playlist parser and buffer seconds
- clip segment range selection
- recording filename generation

### Integration tests
- session start creates rolling playlist
- clip export from staged snapshot
- recording start/stop lifecycle

### Manual smoke tests
- launch 2+ instances with different URLs
- clip while recording
- stop/start recording repeatedly
- close app while recording or clipping in progress

## Definition of done
- Clippiti Player is feature-complete for:
  - watch live stream
  - clip from rolling buffer
  - record stream
- no dependency on StreamKeeper or StreamCondor runtime artifacts
- docs and tests are present in new repo
