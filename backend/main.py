"""
FastAPI application entry point for the Windchill PLM AI Assistant POC.

Run with:
    uvicorn backend.main:app --reload --port 8000

Swagger UI: http://localhost:8000/docs
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router

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

# Allow the React frontend (or Postman) to call the API from localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/", tags=["Root"])
def root():
    return {
        "message": "Windchill PLM AI Assistant POC",
        "docs": "/docs",
        "health": "/api/v1/health",
        "ask": "POST /api/v1/ask",
        "search": "GET /api/v1/search?q=your+query",
    }
