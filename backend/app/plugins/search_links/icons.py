"""Site icons ("favicons"), fetched by the server and converted to a small PNG.

The URLs come from an admin, but a typo must not make the server query the local network:
only http(s) to public addresses, checked again after each redirect. SVG is refused (served
by our own server, it could run scripts).
"""

import asyncio
import io
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

ICON_SIZE = 64
MAX_PAGE_BYTES = 1024 * 1024
MAX_ICON_BYTES = 512 * 1024
MAX_REDIRECTS = 4


class IconError(Exception):
    pass


async def resolve(host: str, port: int) -> list[str]:
    """The addresses of a host (replaced in tests)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def _check_public(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise IconError(f"Not an http(s) address: {url}")
    try:
        addresses = await resolve(
            parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
        )
    except OSError as error:
        raise IconError(f"Unknown host {parts.hostname}") from error
    for address in addresses:
        if not ipaddress.ip_address(address.split("%")[0]).is_global:
            raise IconError(f"{parts.hostname} is a local or private address")


async def _get(http: httpx.AsyncClient, url: str, limit: int) -> tuple[bytes, str, str]:
    """(body, content type, final URL), following redirects to public addresses only."""
    for _ in range(MAX_REDIRECTS + 1):
        await _check_public(url)
        try:
            async with http.stream("GET", url, follow_redirects=False) as response:
                if response.is_redirect and "location" in response.headers:
                    url = urljoin(url, response.headers["location"])
                    continue
                if response.status_code != 200:
                    raise IconError(f"HTTP {response.status_code} for {url}")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data += chunk
                    if len(data) > limit:
                        raise IconError(f"Too large: {url}")
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                return bytes(data), content_type.casefold(), url
        except httpx.HTTPError as error:
            raise IconError(f"Cannot reach {url}: {error}") from error
    raise IconError(f"Too many redirects: {url}")


class _IconLinks(HTMLParser):
    """The `<link rel="icon">` (and apple-touch-icon) of a page, biggest first."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link":
            return
        values = {name: value or "" for name, value in attrs}
        rel = values.get("rel", "").casefold().split()
        href = values.get("href", "")
        if not href or not ("icon" in rel or "apple-touch-icon" in rel) or "mask-icon" in rel:
            return
        if href.casefold().split("?")[0].endswith(".svg") or "svg" in values.get("type", ""):
            return
        size = 180 if "apple-touch-icon" in rel else 0
        for token in values.get("sizes", "").casefold().split():
            width = token.split("x")[0]
            size = max(size, int(width)) if width.isdigit() else size
        self.found.append((size, href))


def _png(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("ICO", "PNG", "JPEG", "GIF", "WEBP", "BMP"):
                raise IconError(f"Unsupported image format {image.format}")
            icon = image.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise IconError("Not an image") from error
    icon.thumbnail((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
    square = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    square.paste(icon, ((ICON_SIZE - icon.width) // 2, (ICON_SIZE - icon.height) // 2))
    output = io.BytesIO()
    square.save(output, format="PNG")
    return output.getvalue()


async def _icon_at(http: httpx.AsyncClient, url: str) -> bytes:
    data, content_type, _ = await _get(http, url, MAX_ICON_BYTES)
    if "svg" in content_type:
        raise IconError("SVG icons are not supported")
    return await asyncio.to_thread(_png, data)


async def fetch(http: httpx.AsyncClient, site_url: str, icon_url: str | None) -> bytes:
    """The site's icon as a PNG: `icon_url` if given, else the icons its home page
    declares, else /favicon.ico. IconError if none works."""
    if icon_url:
        return await _icon_at(http, icon_url)
    parts = urlsplit(site_url)
    home = f"{parts.scheme}://{parts.netloc}/"
    candidates: list[str] = []
    try:
        page, content_type, final = await _get(http, home, MAX_PAGE_BYTES)
        if "html" in content_type:
            parser = _IconLinks()
            parser.feed(page.decode("utf-8", errors="replace"))
            ranked = sorted(parser.found, key=lambda found: -found[0])
            candidates = [urljoin(final, href) for _, href in ranked]
    except IconError:
        pass  # the home page may refuse robots: /favicon.ico can still work
    candidates.append(urljoin(home, "/favicon.ico"))
    last = IconError("No icon")
    for candidate in dict.fromkeys(candidates):
        try:
            return await _icon_at(http, candidate)
        except IconError as error:
            last = error
    raise last
