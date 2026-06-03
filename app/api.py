"""Top-level API router aggregating every module under the API prefix."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.assurance.router import router as assurance_router
from app.modules.identity.router import router as identity_router
from app.modules.meta.router import router as meta_router
from app.modules.operations.router import router as operations_router
from app.modules.reporting.router import router as reporting_router

api_router = APIRouter()
api_router.include_router(meta_router)
api_router.include_router(identity_router)
api_router.include_router(operations_router)
api_router.include_router(assurance_router)
api_router.include_router(reporting_router)
