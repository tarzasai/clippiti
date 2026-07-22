# Architecture Overview

Clippiti is a desktop application built with PyQt6 and python-mpv.
It uses the Streamlink Python API and ffmpeg to build a local rolling HLS buffer, then plays the local playlist through mpv.

## High-Level Structure

```mermaid
flowchart TD
    U[User] --> UI[PyQt UI]
    UI --> APP[App Controller]
    APP --> BE[Buffer Engine]
    APP --> CLIP[Clip Service]
    APP --> SNAP[Snapshot Service]
    APP --> REC[Recording Service]
    APP --> RQ[ffmpeg Job Queue]

    BE --> SL[Streamlink API]
    SL --> PUMP[Stream pump thread]
    PUMP --> FF[ffmpeg]
    FF --> HLS[/local live.m3u8 + segments/]
    HLS --> MPV[mpv via python-mpv]

    HLS --> CLIP
    HLS --> SNAP
    HLS --> REC

    CLIP -->|enqueue export| RQ
    SNAP -->|enqueue extract| RQ
    REC -->|enqueue remux| RQ
    RQ --> FF
```

## C4-Style Container View

```mermaid
C4Context
    title Clippiti Container Diagram
    Person(user, "User", "Watches, clips, records live streams")
    System(clippiti, "Clippiti Desktop App", "PyQt6 application")
    System_Ext(streamlink, "Streamlink", "Python library: resolves plugins and fetches stream data")
    System_Ext(ffmpeg, "ffmpeg", "Builds HLS buffer and handles remux/export")
    System_Ext(mpv, "mpv", "Playback engine via python-mpv")

    Rel(user, clippiti, "Uses")
    Rel(clippiti, streamlink, "Calls in-process for metadata + stream bytes")
    Rel(clippiti, ffmpeg, "Runs for buffering/recording/clipping")
    Rel(clippiti, mpv, "Controls playback")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Key Design Choices

- Startup is asynchronous so the window can open while pipeline initialization is in progress.
- The stream processing path is explicit: Streamlink API stream -> pump thread -> ffmpeg stdin -> HLS output -> local playlist.
- Clipping and recording are service-driven and isolated from UI widgets.
- Snapshots are extracted from the buffered segments via ffmpeg (not mpv screenshots), so saved images keep correct colors and are rotated to match the viewer.
- Post-processing (clip export, recording remux, snapshot extraction) goes through a single shared ffmpeg job queue, so ffmpeg processes never overlap and are controlled from one place.

## Core Runtime Artifacts

- Session directory: `<workdir>/sessions/<session_id>/`
- Live playlist: `<session_dir>/live.m3u8`
- HLS segments: `<session_dir>/seg_*.ts`
- Optional stderr logs per process when debug logging is enabled.
