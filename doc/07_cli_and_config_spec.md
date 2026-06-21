# CLI and Config Specification for Clippiti Player

## Primary UX
User launches one stream session per app process.

Example:

```bash
clippiti "https://example.com/live" best --sl "--twitch-disable-ads"
```

Naming convention:
- distribution/project name: `clippiti-player`
- CLI command: `clippiti`
- Python import namespace: `clippiti` (hyphens are not valid Python module names)

## CLI arguments
Positional (required):
- `url`
- `quality`

Optional:
- `--sl <string>`
- `--config <path>`
- `--workdir <path>`
- `--verbose`

### `--sl` behavior
`--sl` is a pass-through argument string for Streamlink options only (no player args).

Parsing and merge rules:
1. Parse `streamlink.default_args` and CLI `--sl` as shell-style token lists.
2. Build the final Streamlink invocation as:
  `streamlink <default_args_tokens> <cli_sl_args_tokens> <url> <quality>`
3. If both config and CLI provide the same Streamlink flag, CLI takes precedence by appearing later in the argv sequence.

Example:

```bash
clippiti "https://www.twitch.tv/hasanabi" best --sl "--retry-max 5 --stream-segment-timeout 20 --loglevel info"
```

Expected Streamlink argv:

```bash
streamlink --retry-max 5 --stream-segment-timeout 20 --loglevel info https://www.twitch.tv/hasanabi best
```

## Config schema (single-session defaults)

```yaml
general:
  ffmpeg_path: ffmpeg
  segment_seconds: 5
  window_segments: 12
  controls_area: 300
  controls_resize_debounce_ms: 40
  mpv_options: {}
clip:
  dir: ~/Videos/Clippiti/clips
  default_duration: 30
snapshot:
  dir: ~/Pictures/Clippiti/snapshots
  filename_format: "{name}_{timestamp}"
recording:
  dir: ~/Videos/Clippiti/recordings
  filename_format: "{name}_{timestamp}"
  auto_remux_to_mp4: false
streamlink:
  default_args: ""
```

`general.controls_area` controls the quarter-circle corner proximity trigger used by the floating controls panel; larger values make slide-out activation happen earlier while approaching a corner.

`general.controls_resize_debounce_ms` is optional and controls debounce for control-strip repositioning while the window is being resized. Default is `40` ms when omitted.

## `general.mpv_options` policy
`general.mpv_options` is an advanced user map of extra MPV options to apply at player initialization.

Example:

```yaml
general:
  mpv_options:
    hwdec: vaapi-copy
    video_sync: audio
    interpolation: true
```

Rules:
1. Only allowlisted keys are accepted; unknown keys are ignored with a warning.
2. Keys map to MPV properties/options and are normalized from snake_case to MPV-style names when needed.
3. App-required options are always forced by the app and cannot be overridden by config.

Allowlisted `mpv_options` keys (initial set):
- `hwdec`
- `video_sync`
- `interpolation`
- `deband`
- `scale`
- `cscale`
- `dscale`
- `tscale`
- `alang`
- `slang`
- `audio_device`

Forced/blocked options (always controlled by app for render-API embedding):
- `vo` (forced to `libmpv`)
- `osc` (forced disabled; app provides its own controls)
- `wid`
- `force_window`
- `input_default_bindings`
- `input_vo_keyboard`

## Player controls and keybindings

### Volume control
The floating controls panel includes a **mute/volume indicator** button (always visible when collapsed) that shows the current volume level via icon changes:
- 🔇 `audio-volume-muted-symbolic` — muted or volume 0
- 🔈 `audio-volume-low-symbolic` — volume 1–33%
- 🔉 `audio-volume-medium-symbolic` — volume 34–66%
- 🔊 `audio-volume-high-symbolic` — volume 67–100%

Volume can be adjusted via:
1. **Mouse wheel** (when hovering over the video or controls panel):
   - Scroll up: +5% volume
   - Scroll down: −5% volume
2. **Keyboard** (when the player window is focused):
   - `-` and `+` (both number row and numpad)
   - `PgDn` (−5% volume)
   - `PgUp` (+5% volume)

Visual feedback:
- When volume is adjusted via mouse wheel or keyboard, a large horizontal white gradient bar appears on the video (similar to mpv's overlay) and auto-hides after ~1–2 seconds.
- Muted state: icon changes to muted symbol, overlay displays "Muted".

Mute toggle:
- Clicking the volume indicator button toggles mute on/off without affecting the stored volume value.
- The button's icon updates to reflect the current state.

## Session metadata
Streamlink returns a JSON object from `--json`. The fields Clippiti uses:

```json
{
  "plugin": "twitch",
  "metadata": {
    "author": "<channel name>",
    "category": "<game or category>",
    "title": "<stream title>"
  }
}
```

All four values (`plugin`, `author`, `category`, `title`) are extracted and held in the session runtime. If the call fails or returns no `metadata` block, the stream is considered offline or private and the app aborts.

## Session metadata fallback rules
For display name in window title:
1. `metadata.title` from `streamlink --json`
2. URL

For category label:
1. `metadata.category`
2. `unknown`

## Output naming
Clip and recording names should sanitize stream labels by replacing non filename-safe characters with `_`.
Snapshot names should follow the same sanitization rule and be written to the configured snapshot directory.

## Recommended app title format
`Clippiti Player - <plugin> - <author> - <category> - <title>`
