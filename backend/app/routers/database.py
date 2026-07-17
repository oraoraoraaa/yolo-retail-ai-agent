"""Database records endpoint.

``GET /api/v1/database/records`` returns saved retail records, optionally
filtered by ``keyword`` and ``type``. ``GET /api/v1/database/records/{id}``
returns a single record including detection JSON and image refs.
"""

from __future__ import annotations

from typing import Annotated, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.schemas.database import DatabaseQueryResult, DatabaseRecord, DatabaseRecordType
from app.services import get_store
from app.services.auth import AuthUser, get_current_user

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
