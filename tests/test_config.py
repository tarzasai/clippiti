from pathlib import Path

import clippiti.model.config as config_mod


def test_normalize_config_handles_invalid_input() -> None:
  config = config_mod.normalize_config(None)

  assert config["general"]["ffmpeg_path"] == "ffmpeg"
  assert config["clip"]["default_duration"] == 10
  assert config["clip"]["filename_format"] == "{author}.{timestamp}"


def test_normalize_config_clamps_controls_fields_and_section_defaults() -> None:
  raw = {
    "general": {
      "controls_area": "bad",
      "controls_resize_debounce_ms": "bad",
      "controls_position": "invalid",
      "mpv_options": "invalid",
    },
    "clip": "invalid",
    "snapshot": "invalid",
    "recording": "invalid",
    "streamlink": "invalid",
  }
  normalized = config_mod.normalize_config(raw)

  assert normalized["general"]["controls_area"] == 300
  assert normalized["general"]["controls_resize_debounce_ms"] == 40
  assert normalized["general"]["controls_position"] == "bottom-right-vertical"
  assert normalized["general"]["mpv_options"] == {}
  assert isinstance(normalized["clip"], dict)
  assert isinstance(normalized["snapshot"], dict)
  assert isinstance(normalized["recording"], dict)
  assert isinstance(normalized["streamlink"], dict)


def test_normalize_config_handles_non_dict_general() -> None:
  normalized = config_mod.normalize_config({"general": "oops"})
  assert normalized["general"]["controls_area"] == 300
  assert normalized["general"]["controls_position"] == "bottom-right-vertical"


def test_normalize_config_preserves_valid_controls_position() -> None:
  normalized = config_mod.normalize_config({"general": {"controls_position": "top-left-vertical"}})
  assert normalized["general"]["controls_position"] == "top-left-vertical"


def test_load_config_returns_defaults_when_file_missing(tmp_path: Path) -> None:
  loaded = config_mod.load_config(tmp_path / "missing.yaml")
  assert loaded["general"]["ffmpeg_path"] == "ffmpeg"


def test_save_and_load_config_roundtrip(tmp_path: Path) -> None:
  path = tmp_path / "config.yaml"
  data = config_mod.normalize_config({"streamlink": {"default_args": "--retry-max 7"}})

  config_mod.save_config(path, data)
  loaded = config_mod.load_config(path)

  assert loaded["streamlink"]["default_args"] == "--retry-max 7"


def test_resolve_workdir_with_cli_value(tmp_path: Path) -> None:
  resolved = config_mod.resolve_workdir(str(tmp_path))
  assert resolved == tmp_path.resolve()


def test_resolve_workdir_default() -> None:
  assert config_mod.resolve_workdir(None) == Path("/tmp/clippiti").resolve()


def test_resolve_config_path_prefers_cli(tmp_path: Path) -> None:
  config_path = tmp_path / "my.yaml"
  resolved = config_mod.resolve_config_path(str(config_path), workdir=tmp_path)
  assert resolved == config_path.resolve()


def test_resolve_config_path_prefers_existing_global(monkeypatch, tmp_path: Path) -> None:
  global_dir = tmp_path / "global"
  global_dir.mkdir(parents=True)
  global_cfg = global_dir / "clippiti.yaml"
  global_cfg.write_text("general:\n  ffmpeg_path: ffmpeg\n", encoding="utf-8")

  monkeypatch.setattr(
    config_mod.QStandardPaths,
    "writableLocation",
    lambda *_: str(global_dir),
  )

  resolved = config_mod.resolve_config_path(None, workdir=tmp_path / "work")
  assert resolved == global_cfg.resolve()


def test_resolve_config_path_prefers_existing_workdir_config(monkeypatch, tmp_path: Path) -> None:
  workdir = tmp_path / "work"
  workdir.mkdir(parents=True)
  local_cfg = workdir / "config.yaml"
  local_cfg.write_text("general:\n  ffmpeg_path: ffmpeg\n", encoding="utf-8")

  monkeypatch.setattr(config_mod.QStandardPaths, "writableLocation", lambda *_: "")

  resolved = config_mod.resolve_config_path(None, workdir=workdir)
  assert resolved == local_cfg.resolve()


def test_resolve_config_path_falls_back_without_workdir(monkeypatch) -> None:
  monkeypatch.setattr(config_mod.QStandardPaths, "writableLocation", lambda *_: "")
  assert config_mod.resolve_config_path(None, workdir=None) == Path("clippiti.yaml").resolve()


def test_expand_output_dirs_and_ensure_output_dirs(tmp_path: Path) -> None:
  cfg = config_mod.normalize_config(
    {
      "clip": {"dir": str(tmp_path / "clips")},
      "snapshot": {"dir": str(tmp_path / "snaps")},
      "recording": {"dir": str(tmp_path / "recs")},
    }
  )

  expanded = config_mod.expand_output_dirs(cfg)
  assert expanded["clip"] == (tmp_path / "clips")
  assert expanded["snapshot"] == (tmp_path / "snaps")
  assert expanded["recording"] == (tmp_path / "recs")

  config_mod.ensure_output_dirs(cfg)
  assert (tmp_path / "clips").exists()
  assert (tmp_path / "snaps").exists()
  assert (tmp_path / "recs").exists()
