"""API routers."""

from app.routers.audit import router as audit_router
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.database import router as database_router
from app.routers.media import router as media_router
from app.routers.planogram import router as planogram_router
from app.routers.tickets import router as tickets_router

__all__ = [
    "audit_router",
    "auth_router",
    "chat_router",
    "database_router",
    "media_router",
    "planogram_router",
    "tickets_router",
]
