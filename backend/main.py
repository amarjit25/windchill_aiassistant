"""
FastAPI application entry point for the Windchill PLM AI Assistant POC.

Run with:
    uvicorn backend.main:app --reload --port 8000

Swagger UI: http://localhost:8000/docs
"""
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.auth import AUTH_MODE
from backend.api.routes import router

log = logging.getLogger(__name__)

# CORS origins — restrict in production via CORS_ORIGINS env var
# e.g. CORS_ORIGINS=https://plm-assistant.company.com,https://internal.company.com
_cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS = [o.strip() for o in _cors_origins_raw.split(",")]

app = FastAPI(
    title="Windchill PLM AI Assistant",
    description=(
        "A RAG-based AI assistant for PTC Windchill PLM data. "
        "Ask natural language questions about parts, documents, BOMs, and change notices. "
        "Powered by Claude (Anthropic) + Qdrant vector search."
    ),
    version="0.1.0-poc",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.on_event("startup")
def _startup():
    log.info(f"Windchill PLM AI Assistant starting — AUTH_MODE={AUTH_MODE}")
    if AUTH_MODE == "none":
        log.warning(
            "AUTH_MODE=none — API is open to anyone who can reach it. "
            "Set AUTH_MODE=apikey or AUTH_MODE=windchill for production."
        )


@app.get("/", tags=["Root"])
def root():
    return {
        "message": "Windchill PLM AI Assistant POC",
        "auth_mode": AUTH_MODE,
        "docs": "/docs",
        "health": "/api/v1/health",
        "ask": "POST /api/v1/ask",
        "search": "GET /api/v1/search?q=your+query",
    }
