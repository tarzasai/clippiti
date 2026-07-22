"""MPV options builder: merges config defaults with CLI arguments."""

import logging
from copy import deepcopy

import yaml

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
  "vf",
  "af",
  "sub_auto",
  "sub_delay",
  "audio_delay",
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

log = logging.getLogger(__name__)


def build_mpv_options(
  config_options: dict[str, object],
  cli_options_string: str,
) -> dict[str, object]:
  """Merge config default MPV options with CLI-provided options.

  Config options serve as defaults; CLI options override them.
  All options are validated against the allowlist/blocklist.
  Forced options (locked by the application) are always applied last.

  Args:
    config_options: MPV options from config file (default values).
    cli_options_string: Raw CLI options string (from --mpv argument).

  Returns:
    Merged and filtered dict of effective MPV options.
  """
  if not isinstance(config_options, dict):
    config_options = {}

  # Parse CLI options from string
  cli_options = _parse_cli_options_string(cli_options_string)

  # Merge: config defaults + CLI overrides
  merged = _merge_options_dicts(config_options, cli_options)

  # Filter through allowlist and blocklist
  filtered = _filter_mpv_options(merged)

  # Apply forced options (locked by application)
  filtered.update(FORCED_MPV_OPTIONS)

  return filtered


def _normalize_mpv_key(key: object) -> str:
  """Normalize MPV option names across CLI/config styles.

  Examples:
  - '--vf' -> 'vf'
  - 'vf' -> 'vf'
  - '--video-sync' -> 'video_sync'
  - 'video-sync' -> 'video_sync'
  """
  text = str(key).strip()
  if not text:
    return ""
  text = text.lstrip("-")
  return text.replace("-", "_")


def _parse_cli_options_string(cli_options_string: str) -> dict[str, object]:
  """Parse CLI options string into a dict.

  Supports multiple formats:
  - YAML: 'hwdec: auto, vf: hflip, scale: lanczos'
  - Key=value: 'hwdec=auto, vf=hflip'
  - Mixed: 'hwdec: auto, vf=hflip'

  Also accepts leading dashes in keys, e.g. '--vf=hflip'.

  Returns:
    Dict of parsed options, or empty dict if parsing fails.
  """
  if not cli_options_string or not cli_options_string.strip():
    return {}

  # Try YAML parsing first (most flexible)
  try:
    loaded = yaml.safe_load(cli_options_string)
    if isinstance(loaded, dict):
      normalized: dict[str, object] = {}
      for key, value in loaded.items():
        normalized_key = _normalize_mpv_key(key)
        if normalized_key:
          normalized[normalized_key] = value
      log.debug("parsed CLI mpv options (YAML): %s", normalized)
      return normalized
  except Exception as yaml_exc:
    log.debug("YAML parse failed, trying key=value fallback: %s", yaml_exc)

  # Fallback: parse as simple key=value pairs (comma-separated)
  options: dict[str, object] = {}
  for pair in cli_options_string.split(","):
    pair = pair.strip()
    if not pair:
      continue
    if "=" in pair:
      key, val = pair.split("=", 1)
      normalized_key = _normalize_mpv_key(key)
      if not normalized_key:
        continue
      options[normalized_key] = val.strip()
      log.debug("parsed CLI option: %s=%s", normalized_key, val.strip())
  return options


def _merge_options_dicts(
  defaults: dict[str, object],
  overrides: dict[str, object],
) -> dict[str, object]:
  """Merge config defaults with CLI overrides.

  CLI options take precedence over config defaults.

  Args:
    defaults: Config-based default options.
    overrides: CLI-provided options.

  Returns:
    Merged dict with CLI options overriding defaults.
  """
  merged = deepcopy(defaults)
  merged.update(overrides)
  return merged


def _filter_mpv_options(options: dict[str, object]) -> dict[str, object]:
  """Filter options through allowlist and blocklist.

  - Normalizes key styles (leading dashes, hyphen/underscore variants).
  - Blocks options in BLOCKED_MPV_OPTIONS.
  - Allows options in ALLOWLISTED_MPV_OPTIONS.
  - Silently drops any options not in the allowlist.

  Args:
    options: Raw merged options dict.

  Returns:
    Filtered dict containing only safe, allowlisted options.
  """
  filtered: dict[str, object] = {}
  for key, value in options.items():
    normalized_key = _normalize_mpv_key(key)
    if not normalized_key:
      continue
    if normalized_key in BLOCKED_MPV_OPTIONS:
      log.warning("blocked mpv option: %s (application-controlled)", normalized_key)
      continue
    if normalized_key not in ALLOWLISTED_MPV_OPTIONS:
      log.debug("dropped unlisted mpv option: %s", normalized_key)
      continue
    filtered[normalized_key] = value
  return filtered
