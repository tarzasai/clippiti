import clippiti.services.mpv_args as mpv_mod
from clippiti.services.mpv_args import build_mpv_options


def test_build_mpv_options_accepts_key_value_and_yaml() -> None:
  options1 = build_mpv_options({}, "vf=hflip")
  options2 = build_mpv_options({}, "vf: hflip")

  assert options1["vf"] == "hflip"
  assert options2["vf"] == "hflip"


def test_build_mpv_options_normalizes_dashed_keys() -> None:
  options = build_mpv_options({}, "--video-sync=display-resample, --vf=hflip")

  assert options["video_sync"] == "display-resample"
  assert options["vf"] == "hflip"


def test_build_mpv_options_drops_unallowlisted_and_blocks_forced() -> None:
  options = build_mpv_options(
    {"vo": "gpu", "osc": True, "not_allowed": 1, "hwdec": "auto"},
    "",
  )

  assert "not_allowed" not in options
  assert options["vo"] == "libmpv"
  assert options["osc"] is False
  assert options["hwdec"] == "auto"


def test_build_mpv_options_cli_overrides_config() -> None:
  options = build_mpv_options({"vf": "vflip", "hwdec": "no"}, "vf=hflip, hwdec=auto")

  assert options["vf"] == "hflip"
  assert options["hwdec"] == "auto"


def test_build_mpv_options_non_dict_config_is_safe() -> None:
  options = build_mpv_options("bad", "vf=hflip")

  assert options["vf"] == "hflip"
  assert options["vo"] == "libmpv"


def test_parse_fallback_skips_empty_pairs_and_empty_keys() -> None:
  options = build_mpv_options({}, "vf=hflip,,--=bad")
  assert options["vf"] == "hflip"


def test_yaml_parse_exception_falls_back(monkeypatch) -> None:
  def raise_exc(_text: str):
    raise RuntimeError("boom")

  monkeypatch.setattr(mpv_mod.yaml, "safe_load", raise_exc)
  options = build_mpv_options({}, "vf=hflip")
  assert options["vf"] == "hflip"
