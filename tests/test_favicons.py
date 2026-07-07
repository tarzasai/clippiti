"""Tests for clippiti.services.favicons."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

import clippiti.services.favicons as favicons_mod
from clippiti.services.favicons import _FaviconCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _png(width: int = 32, height: int = 32) -> bytes:
  img = Image.new("RGBA", (width, height), color=(200, 100, 50, 255))
  buf = io.BytesIO()
  img.save(buf, format="PNG")
  return buf.getvalue()


def _ico(sizes: list[int] | None = None) -> bytes:
  sizes = sizes or [32]
  imgs = [Image.new("RGBA", (s, s), color=(0, 128, 255, 255)) for s in sizes]
  buf = io.BytesIO()
  imgs[0].save(buf, format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[1:])
  return buf.getvalue()


def _mock_response(*, text: str = "", content: bytes = b"", status: int = 200) -> MagicMock:
  resp = MagicMock()
  resp.text = text
  resp.content = content
  resp.headers = {"content-type": "image/png"}
  resp.status_code = status
  resp.raise_for_status = MagicMock()
  return resp


@pytest.fixture(autouse=True)
def _reset_singleton():
  favicons_mod._cache = None
  yield
  favicons_mod._cache = None


# ---------------------------------------------------------------------------
# _base_url
# ---------------------------------------------------------------------------

def test_base_url_strips_path(tmp_path: Path) -> None:
  cache = _FaviconCache(tmp_path)
  assert cache._base_url("https://www.twitch.tv/streamer?quality=best") == "https://www.twitch.tv"


def test_base_url_preserves_scheme(tmp_path: Path) -> None:
  cache = _FaviconCache(tmp_path)
  assert cache._base_url("http://profiles.myfreecams.com/Model") == "http://profiles.myfreecams.com"


# ---------------------------------------------------------------------------
# disk cache loading
# ---------------------------------------------------------------------------

def test_load_from_disk_populates_mem(tmp_path: Path) -> None:
  fav_dir = tmp_path / "favicons"
  fav_dir.mkdir()
  data = _png()
  (fav_dir / "twitch_32x32.png").write_bytes(data)

  cache = _FaviconCache(tmp_path)

  assert "twitch" in cache._mem
  assert cache._mem["twitch"][32] == data


def test_load_from_disk_ignores_non_32x32(tmp_path: Path) -> None:
  fav_dir = tmp_path / "favicons"
  fav_dir.mkdir()
  (fav_dir / "twitch_16x16.png").write_bytes(_png(16, 16))  # only 32x32 is loaded

  cache = _FaviconCache(tmp_path)

  assert "twitch" not in cache._mem


def test_load_from_disk_empty_dir(tmp_path: Path) -> None:
  cache = _FaviconCache(tmp_path)
  assert cache._mem == {}


# ---------------------------------------------------------------------------
# _discover
# ---------------------------------------------------------------------------

def test_discover_extracts_link_tags(tmp_path: Path) -> None:
  html = (
    "<html><head>"
    '<link rel="icon" href="/static/favicon.ico">'
    '<link rel="apple-touch-icon" href="/apple.png">'
    "</head></html>"
  )
  cache = _FaviconCache(tmp_path)
  with patch("clippiti.services.favicons.requests.get", return_value=_mock_response(text=html)):
    urls = cache._discover("https://example.com")

  assert "https://example.com/static/favicon.ico" in urls
  assert "https://example.com/apple.png" in urls


def test_discover_always_appends_convention_urls(tmp_path: Path) -> None:
  cache = _FaviconCache(tmp_path)
  with patch("clippiti.services.favicons.requests.get", return_value=_mock_response(text="")):
    urls = cache._discover("https://example.com")

  assert "https://example.com/favicon.ico" in urls
  assert "https://example.com/favicon.png" in urls
  assert "https://example.com/favicon.svg" in urls


def test_discover_deduplicates(tmp_path: Path) -> None:
  html = '<link rel="icon" href="/favicon.ico">'  # same as convention URL
  cache = _FaviconCache(tmp_path)
  with patch("clippiti.services.favicons.requests.get", return_value=_mock_response(text=html)):
    urls = cache._discover("https://example.com")

  assert urls.count("https://example.com/favicon.ico") == 1


def test_discover_fallback_on_http_error(tmp_path: Path) -> None:
  cache = _FaviconCache(tmp_path)
  with patch("clippiti.services.favicons.requests.get", side_effect=OSError("timeout")):
    urls = cache._discover("https://example.com")

  assert urls == [
    "https://example.com/favicon.ico",
    "https://example.com/favicon.png",
    "https://example.com/favicon.svg",
  ]


# ---------------------------------------------------------------------------
# _fetch
# ---------------------------------------------------------------------------

def test_fetch_png_success(tmp_path: Path) -> None:
  data = _png(64, 64)
  cache = _FaviconCache(tmp_path)
  with patch("clippiti.services.favicons.requests.get", return_value=_mock_response(content=data)):
    result = cache._fetch("https://example.com/favicon.png", "example", 32)

  assert isinstance(result, bytes)
  assert cache._mem["example"][32] == result
  assert (tmp_path / "favicons" / "example_32x32.png").exists()


def test_fetch_ico_selects_largest_frame(tmp_path: Path) -> None:
  data = _ico([16, 32, 64])
  cache = _FaviconCache(tmp_path)
  with patch("clippiti.services.favicons.requests.get", return_value=_mock_response(content=data)):
    result = cache._fetch("https://example.com/favicon.ico", "example", 32)

  assert result is not None


def test_fetch_rejects_too_small(tmp_path: Path) -> None:
  data = _png(8, 8)
  cache = _FaviconCache(tmp_path)
  with patch("clippiti.services.favicons.requests.get", return_value=_mock_response(content=data)):
    result = cache._fetch("https://example.com/favicon.png", "example", 32)

  assert result is None


def test_fetch_returns_none_on_http_error(tmp_path: Path) -> None:
  cache = _FaviconCache(tmp_path)
  with patch("clippiti.services.favicons.requests.get", side_effect=OSError("404")):
    result = cache._fetch("https://example.com/missing.png", "example", 32)

  assert result is None


def test_fetch_returns_none_on_bad_image(tmp_path: Path) -> None:
  cache = _FaviconCache(tmp_path)
  with patch("clippiti.services.favicons.requests.get", return_value=_mock_response(content=b"not-an-image")):
    result = cache._fetch("https://example.com/favicon.png", "example", 32)

  assert result is None


# ---------------------------------------------------------------------------
# get (cache hit / miss)
# ---------------------------------------------------------------------------

def test_get_returns_cached_without_network(tmp_path: Path) -> None:
  cache = _FaviconCache(tmp_path)
  data = _png()
  cache._mem["twitch"] = {32: data}

  with patch("clippiti.services.favicons.requests.get") as mock_get:
    result = cache.get("https://twitch.tv/channel", "twitch", 32)
    mock_get.assert_not_called()

  assert result == data


def test_get_cache_miss_fetches_and_caches(tmp_path: Path) -> None:
  data = _png(64, 64)
  resp = _mock_response(text="", content=data)
  cache = _FaviconCache(tmp_path)

  with patch("clippiti.services.favicons.requests.get", return_value=resp):
    result = cache.get("https://example.com/channel", "example", 32)

  assert result is not None
  assert cache._mem["example"][32] == result


def test_get_returns_none_when_all_urls_fail(tmp_path: Path) -> None:
  cache = _FaviconCache(tmp_path)
  with patch("clippiti.services.favicons.requests.get", side_effect=OSError("fail")):
    result = cache.get("https://example.com/channel", "example", 32)

  assert result is None


# ---------------------------------------------------------------------------
# get_favicon module-level function (singleton)
# ---------------------------------------------------------------------------

def test_get_favicon_creates_singleton(tmp_path: Path) -> None:
  assert favicons_mod._cache is None
  data = _png(64, 64)
  with patch("clippiti.services.favicons.requests.get", return_value=_mock_response(content=data)):
    favicons_mod.get_favicon("https://example.com/c", "example", tmp_path, size=32)

  assert favicons_mod._cache is not None


def test_get_favicon_reuses_existing_singleton(tmp_path: Path) -> None:
  sentinel = _FaviconCache(tmp_path)
  data = _png()
  sentinel._mem["example"] = {32: data}
  favicons_mod._cache = sentinel

  result = favicons_mod.get_favicon("https://example.com/c", "example", tmp_path, size=32)

  assert result == data
  assert favicons_mod._cache is sentinel
