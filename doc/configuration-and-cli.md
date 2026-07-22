# Configuration and CLI

## CLI Interface

`clippiti <url> <quality> [options] [-- <streamlink args>]`

`<quality>` accepts a comma-separated fallback list (e.g. `720p,best`); each
candidate is tried in order and the first available stream is used.

Options:

- `--mpv`: additional mpv options (YAML mapping or key=value pairs)
- `--config`: explicit config file path
- `--workdir`: explicit runtime workdir path
- `--verbose`: debug logging
- everything after a `--` separator is forwarded to Streamlink's own argument parser

Example (Twitch):

```bash
clippiti https://www.twitch.tv/example_channel best --mpv "vf=hflip" -- --retry-max 5 --twitch-disable-ads
```

Example (YouTube):

```bash
clippiti https://www.youtube.com/watch?v=dQw4w9WgXcQ best
```

## Config Resolution Order

1. `--config <path>`
2. user config location (`clippiti.yaml`) if it already exists
3. `<workdir>/config.yaml` if it already exists
4. fallback to `<workdir>/config.yaml` (or `./clippiti.yaml` when no workdir)

Typical user config locations:

- Linux: `~/.config/clippiti.yaml`
- Windows: `%APPDATA%\clippiti.yaml`
- macOS: `~/Library/Application Support/clippiti.yaml`

Default workdir:

- `/tmp/clippiti`

## Main Config Sections

- `general`
  - `ffmpeg_path`, `segment_seconds`, `window_segments`, `controls_area`, `controls_resize_debounce_ms`, `mpv_options`
- `streamlink`
  - `default_args` (string of Streamlink options, merged before any `--` passthrough args)
- `clip`
  - `dir`, `default_duration`
- `recording`
  - `dir`, `filename_format`, `auto_remux_to_mp4`
- `snapshot`
  - `dir`, `filename_format`

## Recording Output Formats

Recording always captures to **MPEG-TS (`.ts`)** first. TS is chosen for capture because it is a streaming container with no index/`moov` written at the end: if the app crashes or is killed mid-recording, the partial `.ts` is still fully playable, and the source is already TS-based (HLS segments) so the write is a pure stream copy.

The final container depends on `recording.auto_remux_to_mp4` and whether the view was rotated before recording started (rotation is blocked while recording):

| `auto_remux_to_mp4` | rotated before start | final file |
| --- | --- | --- |
| `false` | no | `.ts` (kept as captured) |
| `true` | no | `.mp4` (lossless `-c copy` remux, `+faststart`) |
| `true` | yes | `.mp4` with a display-rotation flag |
| `false` | yes | `.mkv` with a display-rotation flag |

A rotation is stored as a lossless **display-rotation flag** (via ffmpeg `-display_rotation`, `-c copy`), never a re-encode. MPEG-TS cannot carry that flag, so a rotated recording must use a container that can:

- With auto-remux enabled it becomes `.mp4`.
- With auto-remux disabled it falls back to `.mkv` (also lossless and rotation-capable) so the user still avoids an unwanted `.mp4`.

### Player support for the rotation flag

- **`.mp4`** stores rotation in the track display matrix, which is honored by essentially all players (mpv, VLC, browsers, QuickTime) and file-manager thumbnailers.
- **`.mkv`** stores rotation in the Matroska projection element. mpv and ffmpeg-based thumbnailers apply it, but **some players (notably VLC) ignore it** and show the video un-rotated.

If a rotated recording must play correctly in VLC, enable `auto_remux_to_mp4` so the output is `.mp4`.

