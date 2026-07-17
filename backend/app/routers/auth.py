"""Authentication endpoints for store staff."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.schemas.auth import AuthMeResponse, AuthStatusResponse, LoginRequest, LoginResponse
from app.services.auth import AuthUser, authenticate_user, create_access_token, get_current_user, get_optional_user

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
    """Return the current authenticated principal."""
    return AuthMeResponse(id=user.id, username=user.username, role=user.role)
