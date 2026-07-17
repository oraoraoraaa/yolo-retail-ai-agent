"""Serve persisted media files (audit / planogram images)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.services.auth import AuthUser, get_current_user
from app.services.media import resolve_media_path

router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.get("/{file_path:path}")
async def get_media_file(
    file_path: str,
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> FileResponse:
    """Return a stored image by relative ref (e.g. ``audits/rec-0004.jpg``)."""
    path = resolve_media_path(file_path)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
    return FileResponse(path)
