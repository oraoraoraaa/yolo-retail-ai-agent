"""Authentication endpoints for store staff."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.schemas.auth import (
    AuthMeResponse,
    AuthStatusResponse,
    LoginRequest,
    LoginResponse,
    StaffAccountCreate,
    StaffAccountListResponse,
    StaffAccountResponse,
    StaffAccountUpdate,
)
from app.services.auth import (
    AuthUser,
    authenticate_user,
    create_access_token,
    get_current_user,
    require_account_admin,
    require_account_viewer,
    get_optional_user,
)
from app.services.user_store import (
    InvalidRoleError,
    LastOwnerError,
    StaffAccount,
    UserExistsError,
    UserNotFoundError,
    get_user_store,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(
    user: Annotated[AuthUser | None, Depends(get_optional_user)],
) -> AuthStatusResponse:
    """Report whether auth is required and whether the caller is logged in."""
    settings = get_settings()
    if not settings.auth_enabled:
        return AuthStatusResponse(
            auth_enabled=False,
            authenticated=True,
            username=user.username if user else "anonymous",
            role=user.role if user else "admin",
        )
    if user is None:
        return AuthStatusResponse(auth_enabled=True, authenticated=False)
    return AuthStatusResponse(
        auth_enabled=True,
        authenticated=True,
        username=user.username,
        role=user.role,
    )


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    """Exchange username/password for a JWT access token."""
    settings = get_settings()
    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required.",
        )

    if not settings.auth_enabled:
        # Still issue a token so the frontend can stay uniform, but any password works
        # only when auth is disabled and the admin seed user exists — prefer real login.
        user = authenticate_user(username, payload.password)
        if user is None and username == settings.auth_admin_username:
            # Dev convenience when auth is off and seed user password matches env default.
            from app.services.auth import AuthUser

            user = AuthUser(id=0, username=username, role="admin")
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )
    else:
        user = authenticate_user(username, payload.password)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )

    token = create_access_token(user_id=user.id, username=user.username, role=user.role)
    return LoginResponse(
        access_token=token,
        username=user.username,
        role=user.role,
        expires_in_hours=settings.auth_token_ttl_hours,
    )


@router.get("/me", response_model=AuthMeResponse)
async def me(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthMeResponse:
    """Return the current authenticated principal + permission flags."""
    return AuthMeResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        can_write=user.can_write,
        can_view_accounts=user.can_view_accounts,
        can_manage_accounts=user.can_manage_accounts,
    )


# ---------------------------------------------------------------------------
# Account management (owner writes; owner + admin may view)
# ---------------------------------------------------------------------------


def _to_account_response(account: StaffAccount) -> StaffAccountResponse:
    return StaffAccountResponse(
        id=account.id,
        username=account.username,
        role=account.role,
        is_active=account.is_active,
        created_at=account.created_at,
    )


@router.get("/users", response_model=StaffAccountListResponse)
async def list_users(
    _user: Annotated[AuthUser, Depends(require_account_viewer)],
) -> StaffAccountListResponse:
    """List staff accounts. Owner + admin can view; admin cannot modify."""
    accounts = get_user_store().list()
    return StaffAccountListResponse(
        accounts=[_to_account_response(a) for a in accounts],
        total=len(accounts),
    )


@router.post(
    "/users",
    response_model=StaffAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    payload: StaffAccountCreate,
    _user: Annotated[AuthUser, Depends(require_account_admin)],
) -> StaffAccountResponse:
    """Create a staff account. Owner only."""
    try:
        account = get_user_store().create(
            username=payload.username,
            password=payload.password,
            role=payload.role,
            is_active=payload.is_active,
        )
    except UserExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (InvalidRoleError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _to_account_response(account)


@router.patch("/users/{user_id}", response_model=StaffAccountResponse)
async def update_user(
    user_id: int,
    payload: StaffAccountUpdate,
    _user: Annotated[AuthUser, Depends(require_account_admin)],
) -> StaffAccountResponse:
    """Update a staff account (rename / reset password / role / active). Owner only."""
    try:
        account = get_user_store().update(
            user_id,
            username=payload.username,
            password=payload.password,
            role=payload.role,
            is_active=payload.is_active,
        )
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found."
        ) from exc
    except UserExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except LastOwnerError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (InvalidRoleError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _to_account_response(account)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    user: Annotated[AuthUser, Depends(require_account_admin)],
) -> None:
    """Delete a staff account. Owner only; cannot delete self or the last owner."""
    if user.id and user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )
    try:
        get_user_store().delete(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found."
        ) from exc
    except LastOwnerError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
