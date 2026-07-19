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
