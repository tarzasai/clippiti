"""Helpers for Streamlink argument parsing and merge order."""

import shlex


MIN_SEGMENT_TIMEOUT_SECONDS = 45


def parse_args_string(arg_string: str) -> list[str]:
    text = (arg_string or "").strip()
    if not text:
        return []
    return shlex.split(text)


def _clamp_segment_timeout(args: list[str]) -> list[str]:
    normalized: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]

        if token == "--stream-segment-timeout" and i + 1 < len(args):
            raw_value = args[i + 1]
            try:
                value = int(raw_value)
            except ValueError:
                normalized.extend([token, raw_value])
                i += 2
                continue
            normalized.extend([token, str(max(MIN_SEGMENT_TIMEOUT_SECONDS, value))])
            i += 2
            continue

        if token.startswith("--stream-segment-timeout="):
            _, raw_value = token.split("=", 1)
            try:
                value = int(raw_value)
            except ValueError:
                normalized.append(token)
                i += 1
                continue
            normalized.append(f"--stream-segment-timeout={max(MIN_SEGMENT_TIMEOUT_SECONDS, value)}")
            i += 1
            continue

        normalized.append(token)
        i += 1

    return normalized


def merge_streamlink_args(default_args: str, cli_args: str) -> list[str]:
    merged = parse_args_string(default_args) + parse_args_string(cli_args)
    return _clamp_segment_timeout(merged)


def build_streamlink_command(
    url: str,
    quality: str,
    default_args: str,
    cli_args: str,
) -> list[str]:
    return ["streamlink", *merge_streamlink_args(default_args, cli_args), url, quality]
