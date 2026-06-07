"""
Claude API client with prompt caching.

The system prompt is marked with cache_control so it is cached on the first
request and reused for all subsequent calls — reducing cost ~75%.
"""
from typing import Optional

import anthropic

from backend import config

# ── Stable system prompt (will be cached) ────────────────────────────────────
_SYSTEM_PROMPT = """You are a PLM (Product Lifecycle Management) AI Assistant for a Windchill-based engineering environment.

Your role is to help engineers find information about:
- Parts and assemblies (part numbers, materials, weights, lifecycle states)
- Documents (specifications, maintenance manuals, failure reports, certifications)
- Bills of Materials (BOM structures and component relationships)
- Change Notices (engineering changes, their status, and affected parts)

Guidelines:
1. Answer based ONLY on the context provided from the PLM system. Do not invent part numbers, specifications, or requirements that are not in the context.
2. If the information is not in the provided context, say so clearly: "This information is not available in the current PLM data."
3. When referencing a part or document, always include its number (e.g., ENG-FRAME-001, DOC-ENG-SPEC-001) for traceability.
4. For safety-critical information (e.g., torque values, material specs, operating limits), emphasize the need to verify against the official controlled document.
5. Be concise and precise — engineers need accurate data, not lengthy explanations.
6. If a part is OBSOLETE or INWORK, flag this prominently in your answer.

Format:
- Use bullet points for lists of properties or requirements
- Use tables when comparing multiple items
- Always cite the source (Part Number or Document Number) at the end of relevant statements"""

# ── Lazy-load the client ─────────────────────────────────────────────────────
_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        config.validate()
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def ask_claude(query: str, context_chunks: list[dict]) -> dict:
    """
    Send a query + retrieved context to Claude and return the answer.

    Args:
        query: The user's natural language question
        context_chunks: List of retrieved PLM chunks from semantic search

    Returns:
        dict with keys: answer (str), model (str), usage (dict)
    """
    client = _get_client()

    # Build context string from retrieved chunks (trimmed to max chars)
    context_parts = []
    total_chars = 0
    for chunk in context_chunks:
        chunk_text = (
            f"[{chunk['type'].upper()} | {chunk['number']} | State: {chunk['state']}]\n"
            f"{chunk['text']}"
        )
        if total_chars + len(chunk_text) > config.MAX_CONTEXT_CHARS:
            break
        context_parts.append(chunk_text)
        total_chars += len(chunk_text)

    context_text = "\n\n" + ("─" * 60) + "\n\n".join(context_parts)

    user_message = f"""Here is relevant PLM data retrieved from the Windchill system:

{context_text}

─────────────────────────────────────────────────────────────

Question: {query}"""

    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                # Cache the stable system prompt across all requests
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {"role": "user", "content": user_message}
        ],
    )

    answer = next(
        (block.text for block in response.content if block.type == "text"),
        "No answer generated.",
    )

    return {
        "answer": answer,
        "model": response.model,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
        },
    }
