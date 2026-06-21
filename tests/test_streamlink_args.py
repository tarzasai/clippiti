from clippiti.services.streamlink_args import build_streamlink_base_args
from clippiti.services.streamlink_args import build_streamlink_command
from clippiti.services.streamlink_args import build_streamlink_metadata_command
from clippiti.services.streamlink_args import parse_args_string


def _pairs(args: list[str]) -> dict[str, str | None]:
  parsed: dict[str, str | None] = {}
  i = 0
  while i < len(args):
    token = args[i]
    if i + 1 < len(args) and not args[i + 1].startswith("-"):
      parsed[token] = args[i + 1]
      i += 2
    else:
      parsed[token] = None
      i += 1
  return parsed


def test_parse_args_string_empty() -> None:
  assert parse_args_string("") == []
  assert parse_args_string("   ") == []


def test_parse_args_string_non_empty_shell_split() -> None:
  parsed = parse_args_string("--loglevel info --title \"hello world\"")
  assert parsed == ["--loglevel", "info", "--title", "hello world"]


def test_build_streamlink_base_args_cli_overrides_default() -> None:
  default_args = "--retry-max 5 --stream-segment-timeout 45"
  cli_args = "--retry-max 10 --loglevel info"

  merged = build_streamlink_base_args(default_args, cli_args)
  parsed = _pairs(merged)

  assert parsed["--retry-max"] == "10"
  assert parsed["--stream-segment-timeout"] == "45"
  assert parsed["--loglevel"] == "info"


def test_build_streamlink_base_args_handles_bool_flags_and_stray_tokens() -> None:
  default_args = "customtoken --force"
  cli_args = "--force --retry-max 7"

  merged = build_streamlink_base_args(default_args, cli_args)
  parsed = _pairs(merged)

  assert parsed["--force"] is None
  assert parsed["--retry-max"] == "7"
  assert "customtoken" not in merged


def test_build_streamlink_metadata_command_contains_json() -> None:
  cmd = build_streamlink_metadata_command(
    url="https://example.com/live",
    default_args="--retry-max 5",
    cli_args="",
  )

  assert cmd[0] == "streamlink"
  assert "--json" in cmd
  assert cmd[-1] == "https://example.com/live"


def test_build_streamlink_command_contains_stdout_and_quality() -> None:
  cmd = build_streamlink_command(
    url="https://example.com/live",
    quality="best",
    default_args="--retry-max 5",
    cli_args="--stream-segment-timeout 20",
  )

  assert cmd[0] == "streamlink"
  assert "--stdout" in cmd
  assert cmd[-2] == "https://example.com/live"
  assert cmd[-1] == "best"
