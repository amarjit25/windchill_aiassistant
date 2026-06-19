# Windchill PLM AI Assistant

A RAG-based AI assistant for PTC Windchill PLM data. Ask natural language questions about parts, BOMs, documents, and change notices. Powered by Claude (Anthropic) + Qdrant vector search.

```
Engineer asks → FastAPI → Qdrant semantic search → Claude / LiteLLM → Cited answer
                                 ↑
                    Windchill OData REST sync
```

---

## Features

- **Natural language queries** over Parts, BOMs, Documents, and Change Notices
- **Semantic search** via Qdrant vector DB (local or cloud)
- **Multiple LLM providers** — Anthropic API, LiteLLM proxy, AWS Bedrock, Ollama (on-prem)
- **Live Windchill sync** via OData REST with incremental (delta) support
- **Mock data** for local development without a Windchill server
- **PDF content extraction** — indexes the text inside engineering documents
- **Lifecycle filters** — scope queries to RELEASED / INWORK / OBSOLETE objects
- **Prompt caching** — reduces cost ~75% on repeated Claude calls

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI (port 8000)                   │
│  POST /api/v1/ask   GET /api/v1/search   GET /health    │
└────────────────────────┬────────────────────────────────┘
                         │
            ┌────────────▼────────────┐
            │   RAG Chain             │
            │  1. Semantic search     │
            │  2. Build context       │
            │  3. LLM generation      │
            └──────┬──────────────────┘
                   │
        ┌──────────▼──────────┐        ┌────────────────────┐
        │   Qdrant Vector DB  │        │   LLM Provider     │
        │   (local Docker)    │        │   (pick one)       │
        │                     │        │                    │
        │  ▸ parts            │        │  • Anthropic API   │
        │  ▸ bom              │        │  • LiteLLM proxy   │
        │  ▸ documents        │        │  • AWS Bedrock     │
        │  ▸ change_notices   │        │  • Ollama (local)  │
        └─────────────────────┘        └────────────────────┘
                   ▲
        ┌──────────┴──────────┐
        │  Sync Script        │
        │  (full / delta)     │
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │  Windchill OData    │
        │  REST API           │
        │                     │
        │  /ProdMgmt/Parts    │
        │  /ProdMgmt/Parts    │
        │    ('..')/GetBOM    │
        │  /DocMgmt/Documents │
        │  /ChangeMgmt/CNs    │
        └─────────────────────┘
```

---

## Quick Start (mock data, no Windchill needed)

**Prerequisites:** Python 3.11+, Docker

```bash
# 1. Clone and install
git clone https://github.com/amarjit25/windchill_aiassistant.git
cd windchill_aiassistant
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY (or choose a different LLM provider below)

# 3. Start Qdrant
docker-compose up -d qdrant

# 4. Index the mock PLM data
python scripts/index_mock_data.py

# 5. Start the API
uvicorn backend.main:app --reload --port 8000

# 6. Run the test suite
python test_queries.py
```

Swagger UI: http://localhost:8000/docs

---

## Configuration

Copy `.env.example` to `.env` and fill in the relevant section for your setup.

### Windchill connection

```bash
WC_BASE_URL=https://your-windchill-server.company.com
WC_USERNAME=api_service_user
WC_PASSWORD=your_password
WC_SSL_VERIFY=false     # set false for self-signed corporate certs
```

Requires Windchill 11.1 M040+ with OData enabled. Test connectivity before syncing:

```bash
python scripts/sync_windchill.py --test-connection
```

### LLM provider — pick one

#### Option 1: Anthropic API (default)

```bash
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6
```

#### Option 2: LiteLLM proxy (recommended for enterprise)

Most common for organizations that route Claude through an internal gateway:

```bash
LLM_PROVIDER=litellm
LITELLM_URL=https://litellm.company.com/chat/completions
LITELLM_MODEL=claude-sonnet-4-6    # name as registered in your LiteLLM config
LITELLM_API_KEY=your-litellm-api-key
LITELLM_SSL_VERIFY=true
```

To find the exact model name your LiteLLM server exposes:

```bash
curl -H "Authorization: Bearer your-api-key" \
  https://litellm.company.com/models | jq '.data[].id'
```

#### Option 3: AWS Bedrock via internal gateway

```bash
LLM_PROVIDER=claudesonnet4.6
GATEWAY_CLAUDESONNET_URL=https://your-internal-gateway/invoke
GATEWAY_AUTH_TYPE=bearer
GATEWAY_API_TOKEN=your-token
```

#### Option 4: Ollama (fully local, no internet)

```bash
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

---

## Syncing Live Windchill Data

### First run — full sync

```bash
# Sync all parts, BOMs, documents, and change notices
python scripts/sync_windchill.py --full

# Also extract and index PDF document content (slower, richer answers)
python scripts/sync_windchill.py --full --download-docs

# Cap record count for a quick test
python scripts/sync_windchill.py --full --max 100
```

### Subsequent runs — delta sync

```bash
# Only fetch objects modified since the last sync (fast)
python scripts/sync_windchill.py --delta

# Override the delta timestamp manually
python scripts/sync_windchill.py --delta --since 2024-11-01T00:00:00Z
```

Delta sync stores a `.last_sync_timestamp` file in the project root. Schedule it via cron for continuous freshness:

```bash
# Hourly incremental sync
0 * * * * cd /path/to/windchill_aiassistant && .venv/bin/python scripts/sync_windchill.py --delta >> logs/sync.log 2>&1
```

---

## API Reference

### `POST /api/v1/ask`

Ask a natural language question. Returns an answer with cited PLM sources.

```json
{
  "query": "What change notices affect the bearing assembly?",
  "top_k": 6,
  "filter_type": "change_notice",
  "filter_state": "RELEASED"
}
```

`filter_type` options: `part` | `document` | `bom` | `change_notice`  
`filter_state` options: `RELEASED` | `INWORK` | `OBSOLETE`

**Response:**

```json
{
  "answer": "Two change notices affect the bearing assembly...",
  "sources": [
    {
      "type": "change_notice",
      "number": "CN-2024-0047",
      "name": "Bearing Material Update",
      "state": "RELEASED",
      "relevance_score": 0.91
    }
  ],
  "model": "claude-sonnet-4-6",
  "usage": { "input_tokens": 1240, "output_tokens": 312 }
}
```

### `GET /api/v1/search?q=<query>`

Pure semantic search — returns raw matching PLM objects without LLM generation. Useful for debugging what's indexed.

```bash
curl "http://localhost:8000/api/v1/search?q=bearing+failure&filter_type=change_notice"
```

### `GET /api/v1/health`

Returns API status and Qdrant collection stats.

---

## Project Structure

```
windchill_aiassistant/
├── backend/
│   ├── api/
│   │   └── routes.py          # FastAPI endpoints
│   ├── data/
│   │   └── loader.py          # Mock data → indexable chunks
│   ├── llm/
│   │   ├── rag_chain.py       # Orchestrates retrieve → generate
│   │   ├── claude_client.py   # Anthropic API with prompt caching
│   │   ├── litellm_client.py  # LiteLLM proxy (OpenAI-compatible)
│   │   ├── bedrock_proxy_client.py  # Bedrock / on-prem gateway
│   │   └── ollama_client.py   # Local Ollama
│   ├── search/
│   │   ├── indexer.py         # Embed + store in Qdrant
│   │   └── retriever.py       # Semantic search with filters
│   ├── config.py              # All settings from .env
│   └── main.py                # FastAPI app entry point
├── windchill/
│   ├── client.py              # OData HTTP client (Basic Auth, pagination)
│   ├── fetcher.py             # Fetch Parts / BOM / Docs / CNs from OData
│   └── wc_loader.py           # Normalize live API responses → chunks
├── scripts/
│   ├── sync_windchill.py      # Full + delta sync CLI
│   └── index_mock_data.py     # Index mock data for local dev
├── mock_data/                 # Sample PLM data (aerospace engine)
│   ├── parts.json
│   ├── bom.json
│   ├── documents.json
│   └── change_notices.json
├── mock_server/
│   └── windchill_mock.py      # Local mock Windchill OData server
├── docker-compose.yml         # Qdrant
├── test_queries.py            # End-to-end test suite
└── .env.example               # All configurable settings with docs
```

---

## Windchill OData Compatibility

| Windchill Version | OData Namespace | Status |
|---|---|---|
| 12.x | `ProdMgmt/`, `DocMgmt/`, `ChangeMgmt/` | Supported (default) |
| 11.1 M040+ | `PTC.ProdMgmt/`, `PTC.DocMgmt/`, `PTC.ChangeMgmt/` | Supported — update paths in `windchill/fetcher.py` |
| Below 11.1 M040 | Not available | Not supported |

Verify OData is enabled on your server:

```bash
curl -u "user:pass" -k \
  "https://your-server/Windchill/servlet/odata/ProdMgmt/\$metadata"
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| 404 on `ProdMgmt/Parts` | Older Windchill uses `PTC.` prefix | Update endpoint strings in `windchill/fetcher.py` |
| 401 Unauthorized | Wrong credentials or API user not enabled | Check Windchill admin → users → API access |
| SSL certificate error | Self-signed corporate cert | Set `WC_SSL_VERIFY=false` in `.env` |
| 403 on ChangeMgmt | User lacks Change Mgmt read permission | Add API user to a Windchill context with CN read ACL |
| BOM returns empty | Part isn't Assembly type in Windchill | Expected — only assembly-type parts have BOMs |
| LiteLLM 404 | Model name not registered in proxy | Run `curl .../models` to list valid model IDs |
| Poor answer quality | Embedding model too generic for PLM terms | Change `EMBED_MODEL` to `BAAI/bge-base-en-v1.5` |

---

## Important Notes

**Access control:** The vector index does not enforce Windchill ACLs. Ensure the service is deployed in an environment where only authorized users can reach the API, or implement token-based access control in front of it.

**Answer accuracy:** Always cite source part/document numbers (the API returns them in `sources`). For safety-critical values (torques, materials, operating limits), verify against the official controlled document in Windchill before acting on an answer.

**Revision freshness:** Run delta sync regularly so the index stays current with Windchill state changes. Stale data in Qdrant will produce answers based on superseded revisions.

---

## License

MIT
