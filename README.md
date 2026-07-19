# Clippiti
*Cross-platforms livestream player with clipping and recording.*

Clippiti is a PyQt6 desktop app that opens live streams via Streamlink, keeps a rolling local buffer, and lets you take snapshots or save both live and past moments as clips.

## Features

- Live stream playback via Streamlink + mpv
- Rolling HLS buffer pipeline (Streamlink API -> ffmpeg)
- Clip export from buffered timeline
- Recording with optional auto-remux to MP4
- Floating controls, keyboard shortcuts, and OSD feedback
- YAML config with runtime-editable settings dialog
- CLI overrides for Streamlink and mpv options

Supported OS: Linux, Windows, macOS

## Requirements

- Python 3.12+
- Desktop environment that supports PyQt6 apps

### Non-Python dependencies

Clippiti requires these external tools at runtime:

- `mpv` / `libmpv` (used by `python-mpv` for playback)
- `ffmpeg`

`streamlink` is used as a Python library (a `clippiti-player` dependency); Clippiti
calls the Streamlink API in-process rather than spawning a `streamlink` command, so
you do not need a system `streamlink` package on `PATH`.

Install them with your OS package manager.

Linux:

```bash
# Ubuntu / Debian
sudo apt install mpv libmpv2 ffmpeg

# Fedora
sudo dnf install mpv mpv-libs ffmpeg

# Arch Linux
sudo pacman -S mpv ffmpeg
```

macOS:

```bash
brew install mpv ffmpeg
```

Windows (PowerShell, using Scoop):

```powershell
scoop install mpv ffmpeg
```

Verify they are available in `PATH`:

```bash
mpv --version
ffmpeg -version
```

Verify Python-installed Streamlink version from the same environment used to run Clippiti:

```bash
python -m streamlink --version
```

## Install

From PyPI (recommended):

```bash
pip install clippiti-player
```

or with pipx:

```bash
pipx install clippiti-player
```

Run:

```bash
clippiti <url> <quality>
```

### Install from source (development)

```bash
git clone <your-repo-url>
cd clippiti
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Alternative without editable install:

```bash
PYTHONPATH=src ./.venv/bin/python -m clippiti <url> <quality>
```

## Command-line options

```text
positional:
  url                      Stream URL to open
  quality                  Desired stream quality (e.g. best, worst, 720p)

optional:
  --mpv TEXT               Additional mpv options (YAML or key=value)
  --config PATH            Path to config YAML file
  --workdir PATH           Path to runtime working directory
  --verbose                Enable verbose startup logs

Any arguments after a `--` separator are forwarded to Streamlink's own parser.
Run `python -m streamlink --help` to see the available Streamlink options.
```

Example:

```bash
clippiti https://www.twitch.tv/example_channel best --mpv "vf=hflip" -- --retry-max 5 --twitch-disable-ads
```

## Companion App: Lurkiti

If you want a tray app that monitors your favorite livestreams and opens them directly in your player, check out my [**Lurkiti**](https://github.com/tarzasai/Lurkiti).

Lurkiti is a lightweight desktop companion for stream monitoring and quick one-click launch into Clippiti or any other Streamlink supported media player.

## Configuration

Clippiti stores configuration in YAML.

Resolution order:

1. `--config <path>` if provided
2. User config location (`clippiti.yaml`) if it exists
3. `<workdir>/config.yaml` if it exists
4. Fallback to `<workdir>/config.yaml` (or `./clippiti.yaml` if no workdir)

User config location (`clippiti.yaml`) is typically:

- Linux: `~/.config/clippiti.yaml`
- Windows: `%APPDATA%\clippiti.yaml`
- macOS: `~/Library/Application Support/clippiti.yaml`

Default workdir is:

- `/tmp/clippiti`

## Development

Install dev/test deps (already included in `requirements.txt`):

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Run tests:

```bash
PYTHONPATH=src ./.venv/bin/python -m pytest -q
```

## Documentation

- [Technical documentation index](doc/README.md)

## Troubleshooting

- Stream resolution fails:
  - Verify URL is online/public
  - Verify the `streamlink` package resolves the URL (`python -m streamlink <url>`)
- Playback pipeline does not start:
  - Verify `ffmpeg` is installed and reachable
  - Use `--verbose` to inspect startup logs
- mpv/video issues:
  - Verify `python-mpv` is installed
  - Try with simpler `--mpv` options first

## License

MIT License - see `LICENSE` if present in this repository.

## Acknowledgments

- Streamlink
- ffmpeg
- PyQt6
- python-mpv

## Screenshots

![Main Window](https://raw.githubusercontent.com/tarzasai/Clippiti/main/doc/media/main-window.png)
![Clip Dialog](https://raw.githubusercontent.com/tarzasai/Clippiti/main/doc/media/clip-dialog.png)
![Settings Dialog](https://raw.githubusercontent.com/tarzasai/Clippiti/main/doc/media/settings-dialog.png)
