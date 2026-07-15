"""Database records endpoint.

``GET /api/v1/database/records`` returns saved retail records, optionally
filtered by ``keyword`` and ``type``.
"""

from __future__ import annotations

from typing import get_args

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.database import DatabaseQueryResult, DatabaseRecordType
from app.services import get_store

router = APIRouter(prefix="/api/v1/database", tags=["database"])

_VALID_TYPES = set(get_args(DatabaseRecordType))


@router.get("/records", response_model=DatabaseQueryResult)
async def query_records(
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
