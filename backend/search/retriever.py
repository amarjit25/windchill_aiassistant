"""
Semantic retriever — takes a user query, embeds it, and searches Qdrant.
"""
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from backend import config
from backend.search.embedder import embed_single


def _get_client() -> QdrantClient:
    return QdrantClient(url=config.QDRANT_URL)


def semantic_search(
    query: str,
    top_k: int = None,
    filter_type: Optional[str] = None,
    filter_state: Optional[str] = None,
) -> list[dict]:
    """
    Search the vector DB for chunks most relevant to the query.

    Args:
        query: Natural language search query
        top_k: Number of results to return (defaults to config.TOP_K_RESULTS)
        filter_type: Optional — restrict to a PLM type: "part", "document",
                     "bom", or "change_notice"
        filter_state: Optional — restrict to lifecycle state e.g. "RELEASED"

    Returns:
        List of result dicts with keys: score, type, number, name, state, text
    """
    if top_k is None:
        top_k = config.TOP_K_RESULTS

    client = _get_client()
    query_vector = embed_single(query)

    # Build optional filters
    qdrant_filter = None
    conditions = []
    if filter_type:
        conditions.append(FieldCondition(key="type", match=MatchValue(value=filter_type)))
    if filter_state:
        conditions.append(FieldCondition(key="state", match=MatchValue(value=filter_state)))
    if conditions:
        qdrant_filter = Filter(must=conditions)

    results = client.search(
        collection_name=config.QDRANT_COLLECTION,
        query_vector=query_vector,
        limit=top_k,
        with_payload=True,
        query_filter=qdrant_filter,
    )

    return [
        {
            "score": round(float(r.score), 4),
            "original_id": r.payload.get("original_id", ""),
            "type": r.payload.get("type", ""),
            "number": r.payload.get("number", ""),
            "name": r.payload.get("name", ""),
            "state": r.payload.get("state", ""),
            "text": r.payload.get("text", ""),
        }
        for r in results
    ]
