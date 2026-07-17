"""Planogram CRUD + detection matching endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.common import CamelModel
from app.schemas.planogram import (
    Planogram,
    PlanogramCreate,
    PlanogramListResult,
    PlanogramMatchRequest,
    PlanogramMatchResult,
    PlanogramUpdate,
)
from app.services.auth import AuthUser, get_current_user
from app.services.planogram_match import match_planogram
from app.services.planogram_store import get_planogram_store
from app.services.store import get_store

router = APIRouter(prefix="/api/v1/planograms", tags=["planograms"])


class ActivePlanogramBody(CamelModel):
    """Body for setting the active planogram used by audits."""

    planogram_id: str | None = None


class ActivePlanogramResult(CamelModel):
    active_planogram_id: str | None = None


@router.get("", response_model=PlanogramListResult)
async def list_planograms(
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> PlanogramListResult:
    store = get_planogram_store()
    return PlanogramListResult(
        planograms=store.list(),
        active_planogram_id=store.get_active_id(),
    )


@router.put("/active", response_model=ActivePlanogramResult)
async def set_active_planogram(
    payload: ActivePlanogramBody,
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> ActivePlanogramResult:
    """Must be registered before ``/{planogram_id}`` so ``active`` is not captured as an id."""
    store = get_planogram_store()
    try:
        active_id = store.set_active(payload.planogram_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planogram not found.") from exc
    return ActivePlanogramResult(active_planogram_id=active_id)


@router.post("", response_model=Planogram, status_code=status.HTTP_201_CREATED)
async def create_planogram(
    payload: PlanogramCreate,
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> Planogram:
    if not payload.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Planogram name is required.")
    planogram = get_planogram_store().create(payload)
    filled = sum(1 for slot in planogram.slots if slot.item_name or slot.sku)
    get_store().add(
        "inventory",
        title=f"Planogram · {planogram.name}",
        summary=f"Created planogram with {len(planogram.slots)} drawn region(s) ({filled} labeled).",
    )
    return planogram


@router.get("/{planogram_id}", response_model=Planogram)
async def get_planogram(
    planogram_id: str,
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> Planogram:
    planogram = get_planogram_store().get(planogram_id)
    if planogram is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planogram not found.")
    return planogram


@router.put("/{planogram_id}", response_model=Planogram)
async def update_planogram(
    planogram_id: str,
    payload: PlanogramUpdate,
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> Planogram:
    try:
        planogram = get_planogram_store().update(planogram_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planogram not found.") from exc
    get_store().add(
        "inventory",
        title=f"Planogram · {planogram.name}",
        summary=f"Updated planogram · {len(planogram.slots)} drawn region(s).",
    )
    return planogram


@router.delete("/{planogram_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_planogram(
    planogram_id: str,
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> None:
    try:
        get_planogram_store().delete(planogram_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planogram not found.") from exc


@router.post("/{planogram_id}/match", response_model=PlanogramMatchResult)
async def match_planogram_detections(
    planogram_id: str,
    payload: PlanogramMatchRequest,
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> PlanogramMatchResult:
    planogram = get_planogram_store().get(planogram_id)
    if planogram is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planogram not found.")
    return match_planogram(planogram, payload.vision_model_response)
