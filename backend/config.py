"""
Configuration management for Windchill PLM AI Assistant.
Reads all settings from environment variables (loaded via .env file).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Anthropic / Claude ──────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")

# ── Vector DB (Qdrant) ──────────────────────────────────────────────────────
QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "windchill_poc")

# ── Embedding Model ─────────────────────────────────────────────────────────
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBED_DIM: int = 384

# ── Mock Data ───────────────────────────────────────────────────────────────
MOCK_DATA_DIR: Path = Path(__file__).parent.parent / "mock_data"

# ── RAG Settings ────────────────────────────────────────────────────────────
TOP_K_RESULTS: int = int(os.getenv("TOP_K_RESULTS", "6"))
MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "8000"))

# ── LLM Provider ────────────────────────────────────────────────────────────
# "claude"         → Anthropic API (requires ANTHROPIC_API_KEY)
# "ollama"         → local Ollama server (no internet / no API key)
# "claudesonnet4.6"→ Bedrock-hosted Claude via internal gateway
# "llama3-8b"      → on-premise hosted Llama3 8B
# "llama3-70b"     → on-premise hosted Llama3 70B
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "claude")

# Ollama settings (only used when LLM_PROVIDER=ollama)
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.1")

# ── LiteLLM proxy settings (only used when LLM_PROVIDER=litellm) ────────────
LITELLM_URL: str = os.getenv("LITELLM_URL", "")
LITELLM_MODEL: str = os.getenv("LITELLM_MODEL", "claude-sonnet-4-6")
LITELLM_API_KEY: str = os.getenv("LITELLM_API_KEY", "")
LITELLM_SSL_VERIFY: bool = os.getenv("LITELLM_SSL_VERIFY", "true").lower() != "false"

# ── On-premise / Bedrock gateway settings ───────────────────────────────────
# Each model has its own invoke URL since they are hosted on different infra.
# claudesonnet4.6 → Bedrock via internal API gateway
GATEWAY_CLAUDESONNET_URL: str = os.getenv(
    "GATEWAY_CLAUDESONNET_URL",
    "https://gpt4ifx.ifx.com/model/claudesonnet4/invoke",
)
# llama3-8b / llama3-70b → on-premise servers
GATEWAY_LLAMA3_8B_URL: str = os.getenv("GATEWAY_LLAMA3_8B_URL", "")
GATEWAY_LLAMA3_70B_URL: str = os.getenv("GATEWAY_LLAMA3_70B_URL", "")

# Auth — bearer | apikey | none  (applied to whichever gateway is called)
GATEWAY_AUTH_TYPE: str = os.getenv("GATEWAY_AUTH_TYPE", "bearer")
GATEWAY_API_TOKEN: str = os.getenv("GATEWAY_API_TOKEN", "")
GATEWAY_SSL_VERIFY: bool = os.getenv("GATEWAY_SSL_VERIFY", "true").lower() != "false"

# ── Data Source ─────────────────────────────────────────────────────────────
# true  → read from mock_data/ JSON files (default, safe for local dev)
# false → fetch live data from Windchill REST API
USE_MOCK_DATA: bool = os.getenv("USE_MOCK_DATA", "true").lower() == "true"

# ── Windchill REST API ───────────────────────────────────────────────────────
WINDCHILL_BASE_URL: str = os.getenv("WINDCHILL_BASE_URL", "")

# Auth type: "basic" (username+password) or "oauth2" (client credentials)
WINDCHILL_AUTH_TYPE: str = os.getenv("WINDCHILL_AUTH_TYPE", "basic")

# Basic auth credentials
WINDCHILL_USERNAME: str = os.getenv("WINDCHILL_USERNAME", "")
WINDCHILL_PASSWORD: str = os.getenv("WINDCHILL_PASSWORD", "")

# OAuth2 client credentials (only used when WINDCHILL_AUTH_TYPE=oauth2)
WINDCHILL_TOKEN_URL: str = os.getenv("WINDCHILL_TOKEN_URL", "")
WINDCHILL_CLIENT_ID: str = os.getenv("WINDCHILL_CLIENT_ID", "")
WINDCHILL_CLIENT_SECRET: str = os.getenv("WINDCHILL_CLIENT_SECRET", "")

# Endpoint paths — these vary by Windchill version; configure in .env
WINDCHILL_PARTS_PATH: str = os.getenv(
    "WINDCHILL_PARTS_PATH", "/servlet/odata/PTC.ProdMgmt/Parts"
)
WINDCHILL_DOCUMENTS_PATH: str = os.getenv(
    "WINDCHILL_DOCUMENTS_PATH", "/servlet/odata/PTC.DocMgmt/Documents"
)
WINDCHILL_BOM_PATH: str = os.getenv(
    "WINDCHILL_BOM_PATH", "/servlet/odata/PTC.ProdMgmt/Parts('{id}')/Uses"
)
WINDCHILL_CN_PATH: str = os.getenv(
    "WINDCHILL_CN_PATH", "/servlet/odata/PTC.ChangeMgmt/ChangeOrders"
)

# SSL verification (set to false only for self-signed certs in dev environments)
WINDCHILL_SSL_VERIFY: bool = os.getenv("WINDCHILL_SSL_VERIFY", "true").lower() != "false"

# Pagination
WINDCHILL_PAGE_SIZE: int = int(os.getenv("WINDCHILL_PAGE_SIZE", "100"))
WINDCHILL_MAX_PAGES: int = int(os.getenv("WINDCHILL_MAX_PAGES", "0"))  # 0 = no limit


def validate() -> None:
    """Raise ValueError if required config is missing."""
    if LLM_PROVIDER == "claude" and not ANTHROPIC_API_KEY:
        raise ValueError(
            "LLM_PROVIDER=claude but ANTHROPIC_API_KEY is not set. "
            "Add it to your .env file, or switch to LLM_PROVIDER=ollama or bedrock."
        )
    if LLM_PROVIDER == "ollama" and not OLLAMA_BASE_URL:
        raise ValueError("LLM_PROVIDER=ollama but OLLAMA_BASE_URL is not set.")

    if LLM_PROVIDER == "claudesonnet4.6" and not GATEWAY_CLAUDESONNET_URL:
        raise ValueError(
            "LLM_PROVIDER=claudesonnet4.6 but GATEWAY_CLAUDESONNET_URL is not set."
        )
    if LLM_PROVIDER == "llama3-8b" and not GATEWAY_LLAMA3_8B_URL:
        raise ValueError(
            "LLM_PROVIDER=llama3-8b but GATEWAY_LLAMA3_8B_URL is not set. "
            "Set it to your on-premise Llama3 8B invoke URL."
        )
    if LLM_PROVIDER == "llama3-70b" and not GATEWAY_LLAMA3_70B_URL:
        raise ValueError(
            "LLM_PROVIDER=llama3-70b but GATEWAY_LLAMA3_70B_URL is not set. "
            "Set it to your on-premise Llama3 70B invoke URL."
        )
    if not USE_MOCK_DATA:
        missing = [
            name for name, val in {
                "WINDCHILL_BASE_URL": WINDCHILL_BASE_URL,
                "WINDCHILL_USERNAME": WINDCHILL_USERNAME,
                "WINDCHILL_PASSWORD": WINDCHILL_PASSWORD,
            }.items()
            if not val
        ]
        if WINDCHILL_AUTH_TYPE == "oauth2":
            missing += [
                name for name, val in {
                    "WINDCHILL_TOKEN_URL": WINDCHILL_TOKEN_URL,
                    "WINDCHILL_CLIENT_ID": WINDCHILL_CLIENT_ID,
                    "WINDCHILL_CLIENT_SECRET": WINDCHILL_CLIENT_SECRET,
                }.items()
                if not val
            ]
        if missing:
            raise ValueError(
                f"USE_MOCK_DATA=false but these required vars are not set: "
                f"{', '.join(missing)}"
            )
