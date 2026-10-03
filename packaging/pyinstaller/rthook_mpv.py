# PyInstaller runtime hook: make the bundled libmpv discoverable before
# `import mpv` runs, on every platform.
#
# python-mpv locates libmpv through ctypes.util.find_library ('mpv' on
# Linux/macOS, 'mpv-2.dll' on Windows). That lookup does not reliably consult
# the bundle directory / LD_LIBRARY_PATH, so we patch find_library to return the
# libmpv shipped inside the frozen app when present.
import ctypes.util
import os
import sys

_MEIPASS = getattr(sys, "_MEIPASS", None)

if _MEIPASS:
  if os.name == "nt":
    os.environ["PATH"] = _MEIPASS + os.pathsep + os.environ.get("PATH", "")
    _add_dll_directory = getattr(os, "add_dll_directory", None)
    if _add_dll_directory is not None:
      try:
        _add_dll_directory(_MEIPASS)
      except OSError:
        pass

  _MPV_NAMES = (
    "libmpv.so.2", "libmpv.so",
    "libmpv.2.dylib", "libmpv.dylib",
    "mpv-2.dll", "libmpv-2.dll", "mpv-1.dll",
  )

  def _bundled_libmpv():
    for name in _MPV_NAMES:
      candidate = os.path.join(_MEIPASS, name)
      if os.path.isfile(candidate):
        return candidate
    return None

  _original_find_library = ctypes.util.find_library

  def _find_library(name):
    direct = os.path.join(_MEIPASS, os.path.basename(name))
    if os.path.isfile(direct):
      return direct
    if name == "mpv" or os.path.basename(name).lower().startswith("mpv"):
      bundled = _bundled_libmpv()
      if bundled is not None:
        return bundled
    return _original_find_library(name)

  ctypes.util.find_library = _find_library
