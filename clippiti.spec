# PyInstaller spec for clippiti (onedir). Built in CI by .github/workflows/release.yml.
#
# Native binaries that cannot be pip-installed are injected by the workflow via
# environment variables, so this spec stays platform-agnostic:
#   CLIPPITI_FFMPEG  -> absolute path to an ffmpeg binary to bundle (optional)
#   CLIPPITI_LIBMPV  -> absolute path to a libmpv shared library to bundle (optional)
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

datas = [("src/clippiti/resources", "clippiti/resources")]
binaries = []
hiddenimports = (
  collect_submodules("clippiti")
  + collect_submodules("streamlink")
  + collect_submodules("streamlink_cli")
)

for pkg in ("streamlink", "streamlink_cli", "wakepy"):
  pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
  datas += pkg_datas
  binaries += pkg_binaries
  hiddenimports += pkg_hidden

ffmpeg = os.environ.get("CLIPPITI_FFMPEG")
if ffmpeg and Path(ffmpeg).is_file():
  binaries.append((ffmpeg, "."))

libmpv = os.environ.get("CLIPPITI_LIBMPV")
if libmpv and Path(libmpv).is_file():
  binaries.append((libmpv, "."))

a = Analysis(
  ["packaging/pyinstaller/clippiti_entry.py"],
  pathex=["src"],
  binaries=binaries,
  datas=datas,
  hiddenimports=hiddenimports,
  hookspath=[],
  runtime_hooks=["packaging/pyinstaller/rthook_mpv.py"],
  excludes=["tkinter"],
  cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
  pyz,
  a.scripts,
  [],
  exclude_binaries=True,
  name="clippiti",
  console=False,
  icon="src/clippiti/resources/icons/app-icon.png",
)

coll = COLLECT(
  exe,
  a.binaries,
  a.datas,
  name="clippiti",
)
