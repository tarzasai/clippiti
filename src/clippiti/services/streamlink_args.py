"""Helpers for Streamlink argument parsing and command construction.

All Streamlink argv assembly should flow through this module so merge behavior is
consistent across logging, metadata probing, and pipeline startup.
"""

import shlex



def parse_args_string(arg_string: str) -> list[str]:
  """Parse argument string into a list of shell-style tokens."""
  text = (arg_string or "").strip()
  if not text:
    return []
  return shlex.split(text)


def _parse_args_to_dict(args_string: str | None) -> dict[str, str | None]:
  """Parse argument string into a dict mapping flags to values.

  Handles both ``--flag=value`` and ``--flag value`` formats.
  Flags without values (boolean flags) map to ``None``.
  """
  if not args_string or not args_string.strip():
    return {}

  tokens = shlex.split(args_string)
  parsed: dict[str, str | None] = {}
  index = 0

  while index < len(tokens):
    token = tokens[index]
    if not token.startswith("-"):
      index += 1
      continue
    if index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
      parsed[token] = tokens[index + 1]
      index += 2
    else:
      parsed[token] = None
      index += 1

  return parsed


def _merge_args_dicts(
  default_dict: dict[str, str | None],
  override_dict: dict[str, str | None],
) -> dict[str, str | None]:
  """Merge config defaults with CLI overrides (CLI wins)."""
  return {**default_dict, **override_dict}


def _dict_to_args_list(options_dict: dict[str, str | None]) -> list[str]:
  """Convert options dict back to a flat CLI token list."""
  args: list[str] = []
  for key, value in options_dict.items():
    if value is None:
      args.append(key)
    else:
      args.append(key)
      args.append(value)
  return args


def build_streamlink_base_args(default_args: str, cli_args: str) -> list[str]:
  """Build merged Streamlink option tokens from config + CLI.

  CLI overrides config values for identical flags.
  """
  default_dict = _parse_args_to_dict(default_args)
  cli_dict = _parse_args_to_dict(cli_args)
  merged_dict = _merge_args_dicts(default_dict, cli_dict)
  return _dict_to_args_list(merged_dict)


def build_streamlink_metadata_command(url: str, default_args: str, cli_args: str) -> list[str]:
  """Build Streamlink command used for ``--json`` metadata probing."""
  return ["streamlink", *build_streamlink_base_args(default_args, cli_args), "--json", url]


def build_streamlink_command(
  url: str,
  quality: str,
  default_args: str,
  cli_args: str,
) -> list[str]:
  """Build Streamlink command used for playback pipeline (stdout)."""
  return ["streamlink", *build_streamlink_base_args(default_args, cli_args), "--stdout", url, quality]
