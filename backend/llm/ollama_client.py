"""
Ollama LLM client — runs open-source models locally (no internet, no API key).

Compatible models: llama3.1, llama3.2, mistral, qwen2.5, phi3, gemma2
Install Ollama: https://ollama.com
Pull a model:   ollama pull llama3.1
"""
from typing import Optional

import requests

from backend import config

# Shared with claude_client so both providers give consistent PLM answers
SYSTEM_PROMPT = """You are a PLM (Product Lifecycle Management) AI Assistant for a Windchill-based engineering environment.

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


def _build_context(context_chunks: list[dict]) -> str:
    """Trim and format retrieved PLM chunks into a context string."""
    parts = []
    total_chars = 0
    for chunk in context_chunks:
        chunk_text = (
            f"[{chunk['type'].upper()} | {chunk['number']} | State: {chunk['state']}]\n"
            f"{chunk['text']}"
        )
        if total_chars + len(chunk_text) > config.MAX_CONTEXT_CHARS:
            break
        parts.append(chunk_text)
        total_chars += len(chunk_text)
    return ("\n\n" + "─" * 60 + "\n\n").join(parts)


def check_ollama_connection() -> bool:
    """Return True if Ollama is reachable and the configured model is available."""
    try:
        resp = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        model_base = config.OLLAMA_MODEL.split(":")[0]
        return any(model_base in m for m in models)
    except Exception:
        return False


def ask_ollama(query: str, context_chunks: list[dict]) -> dict:
    """
    Send a query + retrieved PLM context to a local Ollama model.

    Args:
        query: The user's natural language question
        context_chunks: List of retrieved PLM chunks from semantic search

    Returns:
        dict with keys: answer (str), model (str), usage (dict)
    """
    context_text = _build_context(context_chunks)

    user_message = f"""Here is relevant PLM data retrieved from the Windchill system:

{context_text}

─────────────────────────────────────────────────────────────

Question: {query}"""

    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,        # low temperature for factual PLM answers
            "num_predict": 2048,
        },
    }

    try:
        resp = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=120,               # local models can be slow on first token
        )
        resp.raise_for_status()
    except requests.ConnectionError:
        raise RuntimeError(
            f"Cannot reach Ollama at {config.OLLAMA_BASE_URL}. "
            "Is Ollama running? Start it with: ollama serve"
        )
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            raise RuntimeError(
                f"Model '{config.OLLAMA_MODEL}' not found in Ollama. "
                f"Pull it first: ollama pull {config.OLLAMA_MODEL}"
            )
        raise

    body = resp.json()
    answer = body.get("message", {}).get("content", "No answer generated.")

    usage = {}
    if "prompt_eval_count" in body:
        usage["input_tokens"] = body["prompt_eval_count"]
    if "eval_count" in body:
        usage["output_tokens"] = body["eval_count"]

    return {
        "answer": answer,
        "model": f"ollama/{config.OLLAMA_MODEL}",
        "usage": usage,
    }
