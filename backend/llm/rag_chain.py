"""
RAG chain — orchestrates: query → semantic search → LLM → structured answer.

LLM provider is selected by LLM_PROVIDER in .env:
  claude           → Anthropic API (default)
  ollama           → local Ollama server (no internet required)
  claudesonnet4.6  → Bedrock-hosted Claude via internal gateway
  llama3-8b        → on-premise Llama3 8B
  llama3-70b       → on-premise Llama3 70B
"""
from typing import Optional

from backend import config
from backend.search.retriever import semantic_search

# Models routed through the internal gateway client
_GATEWAY_MODELS = {"claudesonnet4.6", "llama3-8b", "llama3-70b"}


def _ask_llm(query: str, context_chunks: list[dict]) -> dict:
    """Route to the configured LLM provider."""
    if config.LLM_PROVIDER == "ollama":
        from backend.llm.ollama_client import ask_ollama
        return ask_ollama(query=query, context_chunks=context_chunks)

    if config.LLM_PROVIDER in _GATEWAY_MODELS:
        from backend.llm.bedrock_proxy_client import ask_bedrock_proxy
        return ask_bedrock_proxy(query=query, context_chunks=context_chunks)

    # Default: Claude via Anthropic API
    from backend.llm.claude_client import ask_claude
    return ask_claude(query=query, context_chunks=context_chunks)


def answer_query(
    query: str,
    top_k: int = None,
    filter_type: Optional[str] = None,
    filter_state: Optional[str] = None,
) -> dict:
    """
    Full RAG pipeline: query → retrieve → generate.

    Args:
        query: Natural language question from the user
        top_k: How many context chunks to retrieve (default: config value)
        filter_type: Optional filter — "part", "document", "bom", "change_notice"
        filter_state: Optional lifecycle filter — e.g. "RELEASED"

    Returns:
        dict with:
          - answer: LLM's natural language answer
          - sources: List of retrieved PLM objects used for context
          - model: Model identifier used
          - usage: Token usage stats
    """
    # ── Step 1: Retrieve relevant PLM context ─────────────────────────────
    chunks = semantic_search(
        query=query,
        top_k=top_k,
        filter_type=filter_type,
        filter_state=filter_state,
    )

    if not chunks:
        return {
            "answer": "No relevant PLM data found for your query. Try rephrasing or broadening your search.",
            "sources": [],
            "model": "N/A",
            "usage": {},
        }

    # ── Step 2: Generate answer via configured LLM provider ───────────────
    result = _ask_llm(query=query, context_chunks=chunks)

    # ── Step 3: Return structured response ───────────────────────────────
    return {
        "answer": result["answer"],
        "sources": [
            {
                "type": c["type"],
                "number": c["number"],
                "name": c["name"],
                "state": c["state"],
                "relevance_score": c["score"],
            }
            for c in chunks
        ],
        "model": result["model"],
        "usage": result["usage"],
    }
