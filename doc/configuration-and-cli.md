# Configuration and CLI

## CLI Interface

`clippiti <url> <quality> [options]`

Options:

- `--sl`: additional Streamlink arguments
- `--mpv`: additional mpv options (YAML mapping or key=value pairs)
- `--config`: explicit config file path
- `--workdir`: explicit runtime workdir path
- `--verbose`: debug logging

Example (Twitch):

```bash
clippiti https://www.twitch.tv/example_channel best --sl "--retry-max 5" --mpv "vf=hflip"
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
  - `default_args`
- `clip`
  - `dir`, `default_duration`
- `recording`
  - `dir`, `filename_format`, `auto_remux_to_mp4`
- `snapshot`
  - `dir`, `filename_format`
