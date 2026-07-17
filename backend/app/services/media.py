"""Filesystem helpers for audit / planogram image blobs."""

from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from app.config import get_settings

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w/+.-]+);base64,(?P<data>.+)$", re.DOTALL)


def media_root() -> Path:
    return get_settings().media_dir


def ensure_media_dirs() -> None:
    root = media_root()
    (root / "audits").mkdir(parents=True, exist_ok=True)
    (root / "planograms").mkdir(parents=True, exist_ok=True)


def _ext_for_mime(mime: str | None) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    if not mime:
        return ".jpg"
    return mapping.get(mime.lower(), ".bin")


def decode_image_payload(payload: str) -> tuple[bytes, str | None]:
    """Decode a raw base64 or data-URL image into bytes + mime."""
    text = (payload or "").strip()
    if not text:
        return b"", None
    match = _DATA_URL_RE.match(text)
    if match:
        mime = match.group("mime")
        raw = base64.b64decode(match.group("data"), validate=False)
        return raw, mime
    # bare base64
    return base64.b64decode(text, validate=False), None


def save_image_bytes(subdir: str, image_bytes: bytes, *, mime: str | None = None, stem: str | None = None) -> str:
    """Write image bytes under media/<subdir>/ and return a relative ref."""
    ensure_media_dirs()
    if not image_bytes:
        raise ValueError("Cannot save empty image bytes.")
    name = stem or uuid.uuid4().hex
    # Keep filenames filesystem-safe
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or uuid.uuid4().hex
    ext = _ext_for_mime(mime)
    relative = f"{subdir}/{safe}{ext}"
    path = media_root() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    return relative


def save_image_base64(subdir: str, payload: str, *, stem: str | None = None) -> str | None:
    """Persist a base64 / data-URL image and return the relative ref, or None if empty."""
    raw, mime = decode_image_payload(payload)
    if not raw:
        return None
    return save_image_bytes(subdir, raw, mime=mime, stem=stem)


def resolve_media_path(image_ref: str | None) -> Path | None:
    if not image_ref:
        return None
    # Reject path traversal
    cleaned = image_ref.replace("\\", "/").lstrip("/")
    if ".." in cleaned.split("/"):
        return None
    path = (media_root() / cleaned).resolve()
    root = media_root().resolve()
    if not str(path).startswith(str(root)):
        return None
    return path if path.is_file() else None


def media_url_for(image_ref: str | None) -> str | None:
    """Public API path for a stored image ref."""
    if not image_ref:
        return None
    return f"/api/v1/media/{image_ref.lstrip('/')}"
