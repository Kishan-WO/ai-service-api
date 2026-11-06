"""All v1 routes in one router."""

from fastapi import APIRouter

from ai_service.api.v1 import auth, documents, stream

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(documents.router)
api_router.include_router(stream.router)
