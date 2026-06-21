# Buffer Pipeline Reuse Specification

## Objective
Start a rolling HLS buffer immediately when Clippiti Player launches for a given stream URL.

## Required behavior to preserve

1. Build streamlink command with merged default + per-session args.
2. Launch streamlink producing TS to stdout.
3. Launch ffmpeg segmenter consuming pipe stdin and writing HLS playlist/segments.
4. Keep only a sliding window of segments using HLS flags.
5. Expose playlist path for:
- mpv playback source
- recorder source
- clipping source

## Process chain

`streamlink --stdout <url> <quality>` -> `ffmpeg -i pipe:0 -f hls ... live.m3u8`

## Key ffmpeg segmenter settings (reused)
- `-hide_banner`
- `-loglevel error`
- `-c copy`
- `-f hls`
- `-hls_time <segment_seconds>`
- `-hls_list_size <window_segments>`
- `-hls_flags delete_segments+append_list+temp_file`
- `-hls_segment_filename seg_%05d.ts`

## Single-session API proposal

```python
class SessionBufferEngine:
    def start(url: str, quality: str | None, sl_args: str | None) -> SessionRuntime: ...
    def stop(runtime: SessionRuntime) -> None: ...
    def poll_streamlink_output(runtime: SessionRuntime, max_lines: int = 50) -> PollState: ...
    def playlist_has_segment(runtime: SessionRuntime) -> bool: ...
    def playlist_buffer_seconds(runtime: SessionRuntime) -> float: ...
```

## Runtime paths
Per app instance, create isolated work root:
- Linux recommended: `$XDG_RUNTIME_DIR/clippiti/<session_id>/`
- fallback: `/tmp/clippiti/<session_id>/`

Inside session root:
- `live.m3u8`
- `seg_00001.ts`, etc.
- optional diagnostics logs

## Startup readiness gates
- **Step 0 — metadata fetch (before anything else):** call `streamlink --json` for the URL.
  - If it fails or returns no stream data, the stream is offline or private; show an error and exit — do not start the buffer pipeline.
  - On success, populate session metadata (title, author, category) and set the window title.
- App can show "Loading" until first non-comment playlist segment appears.
- Record button enabled once playlist exists and stream pipeline is alive.
- Clip button enabled after minimum buffer threshold (ex: 30s).

## Failure handling
If either streamlink or segmenter exits unexpectedly:
- surface a visible error in UI
- disable clip/record controls
- stop playback
- offer retry/reconnect action

## Multi-instance safety rules
- never use shared fixed temp directory without session subfolder
- never share playlist path between app instances
- remove only own session directory on exit
