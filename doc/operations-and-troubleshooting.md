# Operations and Troubleshooting

## Local Development Commands

Create and activate environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run app:

```bash
PYTHONPATH=src ./.venv/bin/python -m clippiti https://www.twitch.tv/example_channel best
```

Run tests:

```bash
PYTHONPATH=src ./.venv/bin/python -m pytest -q
```

## Runtime Health Checklist

- `streamlink` Python package is importable in the active environment
- `ffmpeg` is installed and in `PATH` (or `general.ffmpeg_path` is correct)
- stream resolution succeeds
- local playlist is created under `<workdir>/sessions/<session_id>/live.m3u8`

## Typical Failures

- Stream resolution error:
  - URL is offline/private/invalid
  - provider-specific authentication or restrictions
  - invalid Streamlink arguments after `--`
- Buffer startup timeout:
  - stream unavailable
  - ffmpeg invocation issue
- Playback issues:
  - mpv runtime or graphics driver issue
  - invalid mpv option override
- Rotated recording or clip plays un-rotated in some players:
  - A rotation is saved as a lossless display-rotation flag. With `auto_remux_to_mp4` disabled, a rotated recording or clip is written as `.mkv`, whose rotation flag is ignored by some players (notably VLC), while mpv and thumbnailers honor it. Enable `auto_remux_to_mp4` (in the `recording` or `clip` config section) to get a `.mp4`, whose rotation flag is honored everywhere. See "Output Formats" in the configuration doc.

## Logging Tips

Use `--verbose` to include startup and process diagnostics.

When debug logs are enabled, stderr logs for pipeline/remux commands may be written to session/output paths and can be inspected after failures.
