"""Clippiti player package."""

__all__ = ["__version__"]

try:
	from ._version import version as __version__  # type: ignore
except Exception:
	__version__ = "0.0.0"
