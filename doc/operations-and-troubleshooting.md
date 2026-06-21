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

- `streamlink` is installed and in `PATH`
- `ffmpeg` is installed and in `PATH` (or `general.ffmpeg_path` is correct)
- metadata probe succeeds
- local playlist is created under `<workdir>/sessions/<session_id>/live.m3u8`

## Typical Failures

- Metadata probe error:
  - URL is offline/private/invalid
  - provider-specific authentication or restrictions
- Buffer startup timeout:
  - stream unavailable
  - streamlink/ffmpeg invocation issue
- Playback issues:
  - mpv runtime or graphics driver issue
  - invalid mpv option override

## Logging Tips

Use `--verbose` to include startup and process diagnostics.

When debug logs are enabled, stderr logs for pipeline/remux commands may be written to session/output paths and can be inspected after failures.
