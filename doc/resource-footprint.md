# Resource Footprint

This document describes the system resources a single running Clippiti instance consumes, the average amounts observed, and the reason each cost exists. It also records which costs are tunable from the app and which are fixed overhead of the underlying stack (Qt + embedded libmpv + GPU driver + Python).

## Measurement Context

Figures below were captured from a live instance playing a 1080p stream, with hardware decoding active (`hwdec=auto-copy`, `hwdec-current=vaapi-copy`).

- Machine: 32-core CPU, AMD GPU (VA-API via Mesa)
- Interpreter: Python 3.14, PyQt6, libmpv 2.5
- Method: `/proc/<pid>/task` for threads, `/proc/<pid>/smaps_rollup` for memory

> Absolute numbers vary by host. Thread count in particular scales with CPU core count because the GPU driver sizes several thread pools to the number of cores.

## Summary (per instance)

| Resource | Average | Notes |
| --- | --- | --- |
| Threads | ~49 | ~27 belong to the GPU driver and scale with CPU cores |
| RSS | ~410 MB | Resident set (includes shared libraries) |
| PSS | ~310 MB | Proportional set (shared pages divided across users) |

A companion `ffmpeg` process (the HLS buffer writer) runs alongside each instance and adds ~3 threads and ~70 MB RSS. This is expected and independent of the in-process footprint.

## Threads

| Group | Count | Source | Reason | Tunable |
| --- | --- | --- | --- | --- |
| Mesa GPU driver | ~27 | `traceq`, `gl`, `gdrv`, shader, disk-cache | Driver thread pools sized to CPU core count; required for GPU decode/render | No (disabling GL threading harms UI responsiveness) |
| Software decode fallback | 4 | `av:h264` | `vd_lavc_threads` fallback pool; idle while GPU decode is active | Marginal (see below) |
| Streamlink HLS | 3 | `TwitchHLSStream` | Segment fetch/download workers | No (provider-driven) |
| mpv core | ~5 | `demux`, `vo`, `core`, `MPVEventHandler`, audio | Demuxing, video output, event loop, audio output | No |
| Audio (PipeWire) | ~3 | `data-loop`, `module-rt`, `mpv/ao/pipewire` | Audio server client threads | No |
| Qt / Wayland | ~4 | `QThread`, `QDBusConnection`, `WaylandEventThr` | UI event handling and windowing | No |
| App | ~2 | `clippiti-stream`, main | Stream pump and main loop | No |

### Software decode fallback threads

`vd_lavc_threads` defaults to `4`. These `av:h264` threads are spawned even when hardware decoding is active, but they sit idle (near-zero CPU time) because the GPU performs the actual decode. They exist as a fallback for hosts without a working hardware decoder, where they *are* load-bearing (single-threaded software decode of 1080p would stutter).

The default is intentionally left at `4` to protect the no-GPU case. On a host where hardware decoding is confirmed working, `general.mpv_options.vd_lavc_threads` can be lowered in the user config to trim these idle threads, but the saving is cosmetic (~3 threads, negligible RAM) and is not recommended as a global default.

## Memory

| Region | Average | Reason | Tunable |
| --- | --- | --- | --- |
| Anonymous (GPU/VAAPI surfaces) | ~150 MB | Hardware decode surface pools; the cost of GPU decoding | No |
| Mesa driver (`libLLVM`, `libgallium`) | ~50 MB | Shader compiler + Gallium driver; mostly shared-clean across GPU apps | No |
| Python heap | ~60 MB | Interpreter objects, app state, lxml/streamlink | No (app is already lean) |
| Qt6 / libmpv / libavcodec | ~40 MB | Shared library code and runtime data | No |
| Wayland shared memory | ~14 MB | Window pixel buffers; scales with window size | Indirect (window size) |
| Demuxer cache | ≤ 32 MB | mpv forward/back cache for the local HLS window | Yes (already capped) |

## Applied Optimizations

The following reductions are already baked into the defaults:

- **Hardware decode (`hwdec=auto-copy`)** — removes the software H.264 decode threads and their CPU/RAM from the active path, while keeping frames in system RAM so rotated snapshots still work.
- **Disabled built-in mpv scripts** (`ytdl`, `stats`, `console`, `select`, `positioning`, `context_menu`, `commands`) — Clippiti drives mpv programmatically, so these are unused; removing them drops ~8 threads.
- **Capped demuxer cache** (`demuxer_max_bytes=32MiB`, `demuxer_max_back_bytes=16MiB`) — mpv only plays the local ~60s rolling HLS window, so a large cache is unnecessary.

See [Configuration and CLI](configuration-and-cli.md) for the option reference.

## Conclusion

After the optimizations above, the per-instance footprint is at the practical floor for an embedded-mpv + Qt + GPU-decode + Python application. The dominant costs — GPU driver threads and GPU/Qt/Python runtime memory — are fixed overhead of the chosen stack and are not safely reducible from the app. The only remaining app-tunable knob (`vd_lavc_threads`) trims idle fallback threads at negligible benefit and is deliberately left conservative.
