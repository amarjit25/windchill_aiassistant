"""
FastAPI routes for the Windchill PLM AI Assistant POC.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.auth import AuthenticatedUser, filter_by_acl, get_current_user
from backend.llm.rag_chain import answer_query
from backend.search.indexer import collection_info
from backend.search.retriever import semantic_search

router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class AskRequest(BaseModel):
    query: str
    top_k: int = 6
    filter_type: Optional[str] = None   # "part" | "document" | "bom" | "change_notice"
    filter_state: Optional[str] = None  # "RELEASED" | "INWORK" | "OBSOLETE"

class Source(BaseModel):
    type: str
    number: str
    name: str
    state: str
    relevance_score: float

class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    model: str
    usage: dict

class SearchResult(BaseModel):
    score: float
    type: str
    number: str
    name: str
    state: str
    text: str

class HealthResponse(BaseModel):
    status: str
    collection: Optional[dict] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, tags=["System"])
def health_check():
    """Health check — no auth required."""
    try:
        info = collection_info()
        return HealthResponse(status="ok", collection=info)
    except Exception as e:
        return HealthResponse(status=f"degraded: {str(e)}", collection=None)


@router.post("/ask", response_model=AskResponse, tags=["RAG"])
def ask(
    request: AskRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Ask a natural language question about PLM data.

    Claude retrieves relevant parts, documents, BOMs, or change notices
    from the vector DB and generates a precise answer.

    Authentication (controlled by AUTH_MODE in .env):
    - none      → no auth required (dev only)
    - apikey    → X-API-Key: sk-your-key
    - windchill → X-WC-Username + X-WC-Password headers

    **Examples:**
    - "What material is the engine frame made of?"
    - "Show me the BOM for the Main Engine Frame"
    - "What change notices affect ENG-BEARING-005?"
    - "What are the FADEC software requirements for EGT limiting?"
    - "List all INWORK parts"
    """
    try:
        result = answer_query(
            query=request.query,
            top_k=request.top_k,
            filter_type=request.filter_type,
            filter_state=request.filter_state,
            user=user,
        )
        return AskResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search", response_model=list[SearchResult], tags=["Search"])
def search(
    q: str = Query(..., description="Search query"),
    top_k: int = Query(8, description="Number of results"),
    filter_type: Optional[str] = Query(None, description="PLM type filter"),
    filter_state: Optional[str] = Query(None, description="Lifecycle state filter"),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Pure semantic search — returns raw matching PLM objects without LLM generation.

    Results are ACL-filtered: in windchill auth mode, only objects the
    authenticated user can read in Windchill are returned.

    **Filter types:** part | document | bom | change_notice
    **Filter states:** RELEASED | INWORK | OBSOLETE
    """
    try:
        results = semantic_search(q, top_k=top_k, filter_type=filter_type, filter_state=filter_state)
        return filter_by_acl(results, user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
