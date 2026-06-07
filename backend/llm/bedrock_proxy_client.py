"""
Gateway client for on-premise and Bedrock-hosted models.

Model → hosting → URL config
─────────────────────────────────────────────────────────────
claudesonnet4.6  AWS Bedrock (internal gateway)  GATEWAY_CLAUDESONNET_URL
llama3-8b        On-premise server               GATEWAY_LLAMA3_8B_URL
llama3-70b       On-premise server               GATEWAY_LLAMA3_70B_URL

Request format is selected automatically by model name:
  claude* → Anthropic/Bedrock format  (anthropic_version field)
  llama*  → Meta Llama3 format        (prompt with special tokens)

To switch models: change LLM_PROVIDER in .env — nothing else changes.
"""
from __future__ import annotations

import json

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from backend import config
from backend.llm.ollama_client import SYSTEM_PROMPT, _build_context


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://",  HTTPAdapter(max_retries=retry))
    return session


def _invoke_url(model: str) -> str:
    """Return the correct invoke URL for the given model name."""
    urls = {
        "claudesonnet4.6": config.GATEWAY_CLAUDESONNET_URL,
        "llama3-8b":        config.GATEWAY_LLAMA3_8B_URL,
        "llama3-70b":       config.GATEWAY_LLAMA3_70B_URL,
    }
    url = urls.get(model)
    if not url:
        raise ValueError(
            f"No invoke URL configured for model '{model}'. "
            f"Available models: {', '.join(urls.keys())}"
        )
    return url


def _auth_headers() -> dict:
    """
    bearer  → Authorization: Bearer <token>
    apikey  → x-api-key: <token>
    none    → no header (network-level / mTLS auth)
    """
    token     = config.GATEWAY_API_TOKEN
    auth_type = config.GATEWAY_AUTH_TYPE.lower()
    if auth_type == "bearer" and token:
        return {"Authorization": f"Bearer {token}"}
    if auth_type == "apikey" and token:
        return {"x-api-key": token}
    return {}


# ── Request builders ──────────────────────────────────────────────────────────

def _claude_payload(user_message: str) -> dict:
    """Anthropic / AWS Bedrock Claude request format."""
    return {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }


def _llama_payload(user_message: str) -> dict:
    """
    Meta Llama3 Bedrock / on-premise request format.
    Uses the Llama3 chat template with special header/footer tokens.
    """
    prompt = (
        "<|begin_of_text|>"
        "<|start_header_id|>system<|end_header_id|>\n"
        f"{SYSTEM_PROMPT}"
        "<|eot_id|>"
        "<|start_header_id|>user<|end_header_id|>\n"
        f"{user_message}"
        "<|eot_id|>"
        "<|start_header_id|>assistant<|end_header_id|>\n"
    )
    return {
        "prompt":      prompt,
        "max_gen_len": 2048,
        "temperature": 0.1,
        "top_p":       0.9,
    }


# ── Response parsers ──────────────────────────────────────────────────────────

def _extract_answer(body: dict, model: str) -> str:
    # Llama3 on-premise / Bedrock: {"generation": "..."}
    if "llama" in model and "generation" in body:
        return body["generation"].strip()

    # Claude Bedrock: {"content": [{"type": "text", "text": "..."}]}
    content = body.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block["text"]

    # Generic proxy passthrough: {"text": "..."}
    if "text" in body:
        return body["text"]

    # Older format fallback: {"completion": "..."}
    if "completion" in body:
        return body["completion"]

    return "No answer generated."


def _extract_usage(body: dict, model: str) -> dict:
    # Llama3: prompt_token_count / generation_token_count
    if "llama" in model:
        return {
            "input_tokens":  body.get("prompt_token_count", 0),
            "output_tokens": body.get("generation_token_count", 0),
        }
    # Claude: usage.input_tokens / usage.output_tokens
    usage = body.get("usage") or {}
    return {
        "input_tokens":  usage.get("input_tokens")  or usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens", 0),
    }


# ── Public entry point ────────────────────────────────────────────────────────

def ask_bedrock_proxy(query: str, context_chunks: list[dict]) -> dict:
    """
    Send a query + PLM context to the configured model gateway.

    Routing:
      LLM_PROVIDER=claudesonnet4.6 → GATEWAY_CLAUDESONNET_URL (Bedrock)
      LLM_PROVIDER=llama3-8b       → GATEWAY_LLAMA3_8B_URL    (on-premise)
      LLM_PROVIDER=llama3-70b      → GATEWAY_LLAMA3_70B_URL   (on-premise)
    """
    model        = config.LLM_PROVIDER
    invoke_url   = _invoke_url(model)
    context_text = _build_context(context_chunks)

    user_message = (
        "Here is relevant PLM data retrieved from the Windchill system:\n\n"
        f"{context_text}\n\n"
        f"{'─' * 61}\n\n"
        f"Question: {query}"
    )

    payload = _llama_payload(user_message) if "llama" in model else _claude_payload(user_message)

    headers = {
        "Content-Type": "application/json",
        "Accept":       "application/json",
        **_auth_headers(),
    }

    try:
        resp = _make_session().post(
            invoke_url,
            headers=headers,
            data=json.dumps(payload),
            timeout=120,
            verify=config.GATEWAY_SSL_VERIFY,
        )
    except requests.ConnectionError:
        raise RuntimeError(
            f"Cannot reach '{model}' at {invoke_url}. "
            "Check the URL and your network/VPN connection."
        )

    if resp.status_code == 401:
        raise RuntimeError(
            f"401 Unauthorized from '{model}' gateway. "
            "Check GATEWAY_API_TOKEN and GATEWAY_AUTH_TYPE in .env."
        )
    if resp.status_code == 403:
        raise RuntimeError(
            f"403 Forbidden from '{model}' gateway. "
            "Your token may not have permission to use this model."
        )
    if resp.status_code == 404:
        raise RuntimeError(
            f"404 — model '{model}' not found at {invoke_url}. "
            "Verify the URL with your infrastructure team."
        )

    resp.raise_for_status()

    body = resp.json()
    return {
        "answer": _extract_answer(body, model),
        "model":  f"gateway/{model}",
        "usage":  _extract_usage(body, model),
    }
