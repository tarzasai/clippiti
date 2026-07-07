"""Favicon fetch-and-cache service (Qt-free)."""

import io
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

log = logging.getLogger("clippiti")


class _FaviconCache:

  def __init__(self, cache_dir: Path) -> None:
    self._dir = cache_dir / "favicons"
    self._dir.mkdir(parents=True, exist_ok=True)
    self._mem: dict[str, dict[int, bytes]] = {}
    self._load_from_disk()

  def _load_from_disk(self) -> None:
    for path in self._dir.glob("*_32x32.png"):
      plugin = path.stem.replace("_32x32", "")
      if plugin not in self._mem:
        self._mem[plugin] = {}
      self._mem[plugin][32] = path.read_bytes()
    log.debug("favicon cache: %d entries loaded", len(self._mem))

  def _base_url(self, url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"

  def _discover(self, base_url: str) -> list[str]:
    urls: list[str] = []
    try:
      log.debug("favicon: fetching page %s", base_url)
      resp = requests.get(base_url, timeout=10, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
      })
      resp.raise_for_status()
      soup = BeautifulSoup(resp.text, "html.parser")
      icon_rels = {"icon", "shortcut icon", "apple-touch-icon",
                   "apple-touch-icon-precomposed", "mask-icon", "fluid-icon"}
      for link in soup.find_all("link"):
        rel = link.get("rel", [])
        if isinstance(rel, list):
          rel = " ".join(rel)
        if any(r in rel.lower() for r in icon_rels):
          href = link.get("href")
          if href:
            resolved = urljoin(base_url, href)
            log.debug("favicon: discovered from html: %s", resolved)
            urls.append(resolved)
    except Exception as exc:
      log.debug("favicon: html parse failed for %s: %s", base_url, exc)
    for path in ("/favicon.ico", "/favicon.png", "/favicon.svg"):
      urls.append(urljoin(base_url, path))
    seen: set[str] = set()
    unique = [u for u in urls if not (u in seen or seen.add(u))]  # type: ignore[func-returns-value]
    log.debug("favicon: %d candidate url(s) for %s", len(unique), base_url)
    return unique

  def _fetch(self, url: str, plugin: str, size: int) -> bytes | None:
    log.debug("favicon: trying %s", url)
    try:
      resp = requests.get(url, timeout=10, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
      })
      resp.raise_for_status()
      log.debug("favicon: got %s bytes content-type=%s", len(resp.content), resp.headers.get("content-type", "?"))
      img = Image.open(io.BytesIO(resp.content))
      log.debug("favicon: opened image mode=%s size=%s n_frames=%s", img.mode, img.size, getattr(img, "n_frames", 1))
      if getattr(img, "n_frames", 1) > 1:
        best, best_img = 0, None
        for i in range(img.n_frames):
          img.seek(i)
          if img.size[0] > best:
            best, best_img = img.size[0], img.copy()
        if best_img:
          log.debug("favicon: selected ico frame %dx%d", best_img.size[0], best_img.size[1])
          img = best_img
      if img.mode != "RGBA":
        img = img.convert("RGBA")
      if img.size[0] < 16 or img.size[1] < 16:
        log.debug("favicon: image too small (%s), skipping", img.size)
        return None
      resized = img.resize((size, size), Image.Resampling.LANCZOS)
      buf = io.BytesIO()
      resized.save(buf, format="PNG")
      data = buf.getvalue()
      (self._dir / f"{plugin}_{size}x{size}.png").write_bytes(data)
      if plugin not in self._mem:
        self._mem[plugin] = {}
      self._mem[plugin][size] = data
      log.info("favicon: cached %s at %dx%d (%d bytes)", plugin, size, size, len(data))
      return data
    except Exception as exc:
      log.debug("favicon: download failed from %s: %s", url, exc)
      return None

  def get(self, url: str, plugin: str, size: int) -> bytes | None:
    log.debug("favicon: get plugin=%s size=%d cache_dir=%s", plugin, size, self._dir)
    if plugin in self._mem and size in self._mem[plugin]:
      log.debug("favicon: cache hit for %s", plugin)
      return self._mem[plugin][size]
    base_url = self._base_url(url)
    log.debug("favicon: cache miss for %s, fetching from %s", plugin, base_url)
    for favicon_url in self._discover(base_url):
      data = self._fetch(favicon_url, plugin, size)
      if data is not None:
        return data
    log.warning("favicon: no usable icon found for %s", plugin)
    return None


_cache: _FaviconCache | None = None


def get_favicon(url: str, plugin: str, cache_dir: Path, size: int = 32) -> bytes | None:
  """Fetch (or return cached) PNG bytes for the platform favicon.

  Safe to call from a background thread. Returns raw PNG bytes or None.
  """
  global _cache
  if _cache is None:
    _cache = _FaviconCache(cache_dir)
  return _cache.get(url, plugin, size)
