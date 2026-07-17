"""Database records + system backup/restore endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, get_args

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.schemas.database import (
    BackupRestoreResult,
    DatabaseClearResult,
    DatabaseQueryResult,
    DatabaseRecord,
    DatabaseRecordType,
)
from app.services import get_store
from app.services.auth import AuthUser, get_current_user
from app.services.backup import export_backup_zip, restore_backup_zip, validate_backup_zip

router = APIRouter(prefix="/api/v1/database", tags=["database"])

_VALID_TYPES = set(get_args(DatabaseRecordType))


@router.get("/records", response_model=DatabaseQueryResult)
async def query_records(
    _user: Annotated[AuthUser, Depends(get_current_user)],
    keyword: str | None = Query(default=None),
    type: str | None = Query(default=None),
) -> DatabaseQueryResult:
    """Return stored records matching the optional filters."""
    record_type: DatabaseRecordType | None = None
    if type and type != "all":
        if type not in _VALID_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown record type '{type}'. Expected one of {sorted(_VALID_TYPES)}.",
            )
        record_type = type  # type: ignore[assignment]

    records = get_store().query(keyword=keyword, record_type=record_type)
    return DatabaseQueryResult(records=records)


@router.delete("/records", response_model=DatabaseClearResult)
async def clear_records(
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> DatabaseClearResult:
    """Delete all database-page records (audits/sku/inventory/chat).

    Also clears on-disk audit images under ``media/audits/``.
    Does **not** clear planograms, users, app settings, or action tickets.
    """
    deleted, media_deleted = get_store().clear_all()
    return DatabaseClearResult(
        deleted=deleted,
        media_deleted=media_deleted,
        message="Database records and audit media cleared.",
    )


@router.get("/records/{record_id}", response_model=DatabaseRecord)
async def get_record(
    record_id: str,
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> DatabaseRecord:
    """Return one record by id (includes detection JSON / image refs)."""
    record = get_store().get(record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found.")
    return record


@router.get("/backup")
async def download_backup(
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> Response:
    """Export the whole system state (DB tables + media) as a zip archive."""
    try:
        payload = export_backup_zip()
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create backup: {exc}",
        ) from exc

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"yolo-retail-backup-{stamp}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/backup/restore", response_model=BackupRestoreResult)
async def restore_backup(
    _user: Annotated[AuthUser, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> BackupRestoreResult:
    """Validate and restore a previously exported backup zip.

    Replaces records, planograms, tickets, users, app settings, and media files.
    """
    if file.content_type and file.content_type not in {
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    }:
        # Browsers are inconsistent; still try to parse as zip below.
        pass

    raw = await file.read()
    try:
        validate_backup_zip(raw)
        restored = restore_backup_zip(raw)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Restore failed: {exc}",
        ) from exc

    return BackupRestoreResult(
        ok=True,
        message=(
            "Backup restored successfully. "
            "Webhook URLs and passwords were not imported from the zip; "
            "re-enter any missing webhook URLs in Ticket Board settings if needed."
        ),
        restored=restored,
    )
