"""Configuration model and lifecycle for Clippiti."""

from copy import deepcopy
from pathlib import Path

from PyQt6.QtCore import QStandardPaths
import yaml

DEFAULT_CONFIG: dict[str, object] = {
    "general": {
        "ffmpeg_path": "ffmpeg",
        "segment_seconds": 5,
        "window_segments": 12,
        "controls_area": 300,
        "controls_resize_debounce_ms": 40,
        "mpv_options": {},
    },
    "clip": {
        "dir": "~/Videos/Clippiti/clips",
        "default_duration": 30,
    },
    "snapshot": {
        "dir": "~/Pictures/Clippiti/snapshots",
        "filename_format": "{name}_{timestamp}",
    },
    "recording": {
        "dir": "~/Videos/Clippiti/recordings",
        "filename_format": "{name}_{timestamp}",
        "auto_remux_to_mp4": False,
    },
    "streamlink": {
        "default_args": "",
    },
}

ALLOWLISTED_MPV_OPTIONS = {
    "hwdec",
    "video_sync",
    "interpolation",
    "deband",
    "scale",
    "cscale",
    "dscale",
    "tscale",
    "alang",
    "slang",
    "audio_device",
}

FORCED_MPV_OPTIONS = {
    "vo": "libmpv",
    "osc": False,
    "input_default_bindings": False,
    "input_vo_keyboard": False,
    "idle": "yes",
    "keep_open": "yes",
    "loop_file": "inf",
    "terminal": False,
}

BLOCKED_MPV_OPTIONS = {
    "vo",
    "osc",
    "wid",
    "force_window",
    "input_default_bindings",
    "input_vo_keyboard",
}


def deep_merge(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_config(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return deepcopy(DEFAULT_CONFIG)
    merged = deep_merge(DEFAULT_CONFIG, raw)

    general = merged.get("general")
    if not isinstance(general, dict):
        general = {}
    controls_area = general.get("controls_area", 300)
    debounce_ms = general.get("controls_resize_debounce_ms", 40)

    try:
        controls_area = int(controls_area)
    except (TypeError, ValueError):
        controls_area = 300
    try:
        debounce_ms = int(debounce_ms)
    except (TypeError, ValueError):
        debounce_ms = 40

    general["controls_area"] = max(50, controls_area)
    general["controls_resize_debounce_ms"] = max(0, debounce_ms)

    mpv_options = general.get("mpv_options", {})
    if not isinstance(mpv_options, dict):
        mpv_options = {}
    general["mpv_options"] = dict(mpv_options)
    merged["general"] = general

    for section in ("clip", "snapshot", "recording", "streamlink"):
        if not isinstance(merged.get(section), dict):
            merged[section] = deepcopy(DEFAULT_CONFIG[section])

    return merged


def load_config(path: Path) -> dict[str, object]:
    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return normalize_config(data)


def save_config(path: Path, config: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def resolve_workdir(cli_workdir: str | None) -> Path:
    if cli_workdir:
        return Path(cli_workdir).expanduser().resolve()
    return Path("/tmp/clippiti").resolve()


def resolve_config_path(cli_config: str | None, workdir: Path | None = None) -> Path:
    if cli_config:
        return Path(cli_config).expanduser().resolve()

    config_root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.ConfigLocation)
    if config_root:
        global_path = (Path(config_root) / "clippiti.yaml").expanduser().resolve()
        if global_path.exists():
            return global_path

    if workdir is not None:
        local_path = (workdir / "config.yaml").resolve()
        if local_path.exists():
            return local_path

    # Default to workdir-local config for deterministic per-run behavior.
    if workdir is not None:
        return (workdir / "config.yaml").resolve()
    return Path("clippiti.yaml").resolve()


def expand_output_dirs(config: dict[str, object]) -> dict[str, Path]:
    clip = Path(str(config["clip"]["dir"])).expanduser()
    snapshot = Path(str(config["snapshot"]["dir"])).expanduser()
    recording = Path(str(config["recording"]["dir"])).expanduser()
    return {
        "clip": clip,
        "snapshot": snapshot,
        "recording": recording,
    }


def ensure_output_dirs(config: dict[str, object]) -> None:
    for path in expand_output_dirs(config).values():
        path.mkdir(parents=True, exist_ok=True)


def effective_mpv_options(config: dict[str, object]) -> dict[str, object]:
    general = config.get("general", {})
    if not isinstance(general, dict):
        general = {}

    raw_options = general.get("mpv_options", {})
    if not isinstance(raw_options, dict):
        raw_options = {}

    options: dict[str, object] = {}
    for key, value in raw_options.items():
        if key in BLOCKED_MPV_OPTIONS:
            continue
        if key in ALLOWLISTED_MPV_OPTIONS:
            options[key] = value

    options.update(FORCED_MPV_OPTIONS)
    return options
