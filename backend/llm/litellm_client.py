"""
LiteLLM proxy client — OpenAI-compatible /chat/completions endpoint.

Configure in .env:
    LLM_PROVIDER=litellm
    LITELLM_URL=https://litellm.company.com/chat/completions
    LITELLM_MODEL=claude-sonnet-4-6          # model name as registered in LiteLLM
    LITELLM_API_KEY=your-litellm-api-key
    LITELLM_SSL_VERIFY=true
"""
from __future__ import annotations

import json
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from backend import config
from backend.llm.ollama_client import SYSTEM_PROMPT, _build_context

log = logging.getLogger(__name__)


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def ask_litellm(query: str, context_chunks: list[dict]) -> dict:
    """
    Send a query + PLM context to a LiteLLM proxy (OpenAI /chat/completions format).
    """
    url = config.LITELLM_URL
    model = config.LITELLM_MODEL
    api_key = config.LITELLM_API_KEY

    if not url:
        raise ValueError("LITELLM_URL is not set in .env")

    context_text = _build_context(context_chunks)
    user_message = (
        "Here is relevant PLM data retrieved from the Windchill system:\n\n"
        f"{context_text}\n\n"
        f"{'─' * 61}\n\n"
        f"Question: {query}"
    )

    payload = {
        "model": model,
        "max_tokens": 2048,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    log.info(f"[LiteLLM] POST {url} model={model}")

    try:
        resp = _make_session().post(
            url,
            headers=headers,
            data=json.dumps(payload),
            timeout=120,
            verify=config.LITELLM_SSL_VERIFY,
        )
    except requests.ConnectionError:
        raise RuntimeError(
            f"Cannot reach LiteLLM proxy at {url}. "
            "Check LITELLM_URL and your VPN/network connection."
        )

    if resp.status_code == 401:
        raise RuntimeError("401 from LiteLLM — check LITELLM_API_KEY.")
    if resp.status_code == 404:
        raise RuntimeError(
            f"404 from LiteLLM — model '{model}' not found. "
            "Check LITELLM_MODEL matches a model registered in your LiteLLM config."
        )

    resp.raise_for_status()

    body = resp.json()
    choices = body.get("choices", [])
    answer = choices[0]["message"]["content"] if choices else "No answer generated."

    usage = body.get("usage", {})
    return {
        "answer": answer,
        "model": f"litellm/{model}",
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }
