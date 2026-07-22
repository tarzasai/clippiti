# Runtime Workflows

This document summarizes the main application workflows.

## 1. Startup and Playback

```mermaid
sequenceDiagram
    participant User
    participant Main as __main__.py
    participant SL as Streamlink API
    participant Buffer as Buffer Engine
    participant UI as UI App

    User->>Main: clippiti <url> <quality>
    Main->>Main: load/normalize config
    Main->>SL: resolve_stream(url, quality, args)
    SL-->>Main: stream + plugin + author + title + category
    Main->>UI: run_app(startup_task=...)
    UI->>Buffer: start_single_session_pipeline(...)
    Buffer-->>UI: runtime with local playlist path
    UI->>UI: set_media_source(live.m3u8)
```

## 2. Clip Export

```mermaid
sequenceDiagram
    participant User
    participant UI
    participant Clip as Clip Service
    participant Queue as Remux Queue

    User->>UI: Open clip dialog and select range
    UI->>Clip: prepare_stage(runtime)
    Clip-->>UI: staged merged.ts + duration
    UI->>Clip: build_export_job(stage, start, end)
    Clip-->>UI: ffmpeg job
    UI->>Queue: enqueue(job)
    Queue-->>UI: job_finished(success/failure)
    UI->>User: OSD status
```

## 3. Recording and Optional Remux

```mermaid
sequenceDiagram
    participant User
    participant UI
    participant Rec as Recording Service
    participant Queue as Remux Queue

    User->>UI: Start recording
    UI->>Rec: start(runtime, cfg)
    Rec-->>UI: recording.ts
    User->>UI: Stop recording
    UI->>Rec: request_stop / stop
    Rec-->>UI: stopped ts path
    UI->>Queue: enqueue remux job (optional)
    Queue-->>UI: job_finished(success/failure)
```

Rotation is blocked while recording. If the view was rotated before recording started, the stop step forces a lossless remux that carries the rotation flag: to mp4 when auto-remux is enabled, otherwise to mkv. Without rotation and with auto-remux disabled the raw `.ts` is kept.

## 4. Snapshot

```mermaid
sequenceDiagram
    participant User
    participant UI
    participant Snap as Snapshot Service
    participant MPV as mpv

    User->>UI: Snapshot (key/toolbar)
    UI->>Snap: capture(runtime, rotation)
    Snap->>MPV: command_async screenshot-to-file (software) to local temp
    MPV-->>Snap: on_done(success/failure)
    Snap->>Snap: rotate temp to match viewer (Pillow), move to output
    Snap-->>UI: snapshot_ready / snapshot_failed
```

mpv's software screenshot (`screenshot-sw`) keeps correct colors under the libmpv render VO but ignores `video-rotate`, so the saved frame is rotated afterwards to match what the viewer sees. The command is async because a synchronous screenshot deadlocks the render API.

## 5. Shutdown

```mermaid
flowchart TD
    A[Window close / app exit] --> B[Cancel startup if pending]
    B --> C[Terminate recording/remux services]
    C --> D[Stop stream pump + terminate ffmpeg runtime process]
    D --> E[Cleanup session artifacts]
    E --> F[Exit]
```
