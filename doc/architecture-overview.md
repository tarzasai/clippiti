# Architecture Overview

Clippiti is a desktop application built with PyQt6 and python-mpv.
It uses Streamlink and ffmpeg to build a local rolling HLS buffer, then plays the local playlist through mpv.

## High-Level Structure

```mermaid
flowchart TD
    U[User] --> UI[PyQt UI]
    UI --> APP[App Controller]
    APP --> BE[Buffer Engine]
    APP --> CLIP[Clip Service]
    APP --> REC[Recording Service]
    APP --> RQ[Remux Queue]

    BE --> SL[Streamlink]
    SL --> FF[ffmpeg]
    FF --> HLS[/local live.m3u8 + segments/]
    HLS --> MPV[mpv via python-mpv]

    CLIP --> HLS
    CLIP --> FF
    REC --> HLS
    REC --> FF
    RQ --> FF
```

## C4-Style Container View

```mermaid
C4Context
    title Clippiti Container Diagram
    Person(user, "User", "Watches, clips, records live streams")
    System(clippiti, "Clippiti Desktop App", "PyQt6 application")
    System_Ext(streamlink, "Streamlink", "Resolves and fetches stream data")
    System_Ext(ffmpeg, "ffmpeg", "Builds HLS buffer and handles remux/export")
    System_Ext(mpv, "mpv", "Playback engine via python-mpv")

    Rel(user, clippiti, "Uses")
    Rel(clippiti, streamlink, "Requests metadata + stream bytes")
    Rel(clippiti, ffmpeg, "Runs for buffering/recording/clipping")
    Rel(clippiti, mpv, "Controls playback")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Key Design Choices

- Startup is asynchronous so the window can open while pipeline initialization is in progress.
- The stream processing path is explicit: Streamlink stdout -> ffmpeg HLS output -> local playlist.
- Clipping and recording are service-driven and isolated from UI widgets.
- Post-processing (remux/export) uses a queue service to avoid overlapping ffmpeg process control.

## Core Runtime Artifacts

- Session directory: `<workdir>/sessions/<session_id>/`
- Live playlist: `<session_dir>/live.m3u8`
- HLS segments: `<session_dir>/seg_*.ts`
- Optional stderr logs per process when debug logging is enabled.
