from fastapi import APIRouter

from .public import router as public_router
from .auth import router as auth_router
from .user import router as user_router
from .admin import router as admin_router
from .api import router as api_router

__all__ = [
    "public_router",
    "auth_router",
    "user_router",
    "admin_router",
    "api_router",
]
