# Windchill PLM AI Assistant — Deployment Guide

## What you are shipping

```
windchillAI/
├── backend/                  ← FastAPI application (ship this)
│   ├── main.py               ← App entry point
│   ├── config.py             ← All config read from environment variables
│   ├── api/routes.py         ← REST endpoints (/ask, /search, /health)
│   ├── data/
│   │   ├── loader.py         ← Switches between mock and live data
│   │   └── windchill_client.py ← Windchill REST API connector
│   ├── search/
│   │   ├── embedder.py       ← Converts text to vectors (runs locally)
│   │   ├── indexer.py        ← Writes vectors to Qdrant
│   │   └── retriever.py      ← Searches vectors in Qdrant
│   └── llm/
│       ├── claude_client.py  ← Sends query + context to Claude API
│       └── rag_chain.py      ← Orchestrates retrieve → generate
├── scripts/
│   ├── index_mock_data.py    ← One-off: index mock JSON data
│   └── sync_windchill.py     ← Full or delta sync from live Windchill
├── mock_data/                ← Sample JSON (dev/testing only)
├── docker-compose.yml        ← Starts Qdrant vector DB
├── requirements.txt          ← Python dependencies
└── .env.example              ← Copy this to .env and fill in values
```

**Do NOT ship:**
- `.venv/` — recreated on the target server with `pip install`
- `.env` — contains secrets; configure separately on each environment
- `mock_data/` — optional, only needed if `USE_MOCK_DATA=true`

---

## Prerequisites on the target server

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | 3.9 works but requires `Optional[]` syntax (already fixed) |
| Docker + Docker Compose | Any recent | For running Qdrant |
| Network access to Windchill | — | Same network/VPN as Windchill server |
| Network access to Anthropic API | — | Outbound HTTPS to `api.anthropic.com` |

---

## Step 1 — Copy the code to the server

Copy everything **except** `.venv/` and `.env`:

```bash
# Option A: clone from Git (recommended)
git clone https://github.com/your-org/windchillAI.git
cd windchillAI

# Option B: rsync from your Mac
rsync -av --exclude='.venv' --exclude='.env' --exclude='__pycache__' \
  /Users/pattanaikamarjit/gitrepo/windchillAI/ user@server:/opt/windchillAI/
```

---

## Step 2 — Create the Python virtual environment

```bash
cd /opt/windchillAI

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

> **Note:** `sentence-transformers` downloads a ~90 MB model on first run.
> If the server has no internet access, download the model on a machine that does
> and copy it across (see "Air-gapped installation" at the end).

---

## Step 3 — Configure environment variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
nano .env        # or vim, or any editor
```

### Minimum required values

```dotenv
# Your Anthropic API key — get it from console.anthropic.com
ANTHROPIC_API_KEY=sk-ant-api03-...

# Which Claude model to use
CLAUDE_MODEL=claude-haiku-4-5

# Qdrant (leave as-is if running via Docker Compose on the same server)
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=windchill_poc

# Set to false to connect to live Windchill instead of mock data
USE_MOCK_DATA=false
```

### Windchill connection (when USE_MOCK_DATA=false)

```dotenv
WINDCHILL_BASE_URL=https://your-windchill-host.company.com/Windchill
WINDCHILL_AUTH_TYPE=basic          # or oauth2
WINDCHILL_USERNAME=service-account
WINDCHILL_PASSWORD=secret

# Endpoint paths — confirm with your Windchill admin
WINDCHILL_PARTS_PATH=/servlet/odata/PTC.ProdMgmt/Parts
WINDCHILL_DOCUMENTS_PATH=/servlet/odata/PTC.DocMgmt/Documents
WINDCHILL_BOM_PATH=/servlet/odata/PTC.ProdMgmt/Parts('{id}')/Uses
WINDCHILL_CN_PATH=/servlet/odata/PTC.ChangeMgmt/ChangeOrders

# Pagination (100 per page, no page limit)
WINDCHILL_PAGE_SIZE=100
WINDCHILL_MAX_PAGES=0

# Set to false only if Windchill has a self-signed SSL certificate
WINDCHILL_SSL_VERIFY=true
```

### OAuth2 (if your Windchill uses SSO/OAuth instead of Basic Auth)

```dotenv
WINDCHILL_AUTH_TYPE=oauth2
WINDCHILL_TOKEN_URL=https://your-windchill-host/Windchill/oauth2/token
WINDCHILL_CLIENT_ID=your-client-id
WINDCHILL_CLIENT_SECRET=your-client-secret
```

---

## Step 4 — Start Qdrant (vector database)

```bash
docker-compose up -d qdrant

# Verify it is running
curl http://localhost:6333/readyz
# Expected: {"result":true,"status":"ok","time":...}
```

---

## Step 5 — Index data into Qdrant

### Option A — Mock data (for testing without Windchill)

```bash
source .venv/bin/activate
python scripts/index_mock_data.py --recreate

# Check what was indexed
python scripts/index_mock_data.py --info
```

### Option B — Live Windchill data

First test the connection:

```bash
python scripts/sync_windchill.py --test-connection
```

Then run a full sync (drops existing data and reindexes everything):

```bash
python scripts/sync_windchill.py --full
```

For subsequent runs, use delta sync (only fetches objects changed since last sync):

```bash
python scripts/sync_windchill.py --delta
```

---

## Step 6 — Start the API server

### For testing / development

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### For production (no --reload, multiple workers)

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
```

The API is now available at:
- **Swagger UI (interactive docs):** `http://server-ip:8000/docs`
- **Health check:** `http://server-ip:8000/api/v1/health`
- **Ask endpoint:** `POST http://server-ip:8000/api/v1/ask`
- **Search endpoint:** `GET http://server-ip:8000/api/v1/search?q=engine+frame`

---

## Step 7 — Test it

```bash
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "What material is the engine frame made of?"}' \
  | python3 -m json.tool
```

---

## Step 8 — Keep data in sync (production)

Set up a cron job to run delta sync automatically:

```bash
crontab -e
```

Add (runs every night at 2 AM):

```
0 2 * * * cd /opt/windchillAI && .venv/bin/python scripts/sync_windchill.py --delta >> /var/log/windchill_sync.log 2>&1
```

---

## Running as a system service (optional)

Create `/etc/systemd/system/windchill-ai.service`:

```ini
[Unit]
Description=Windchill PLM AI Assistant
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=your-user
WorkingDirectory=/opt/windchillAI
EnvironmentFile=/opt/windchillAI/.env
ExecStart=/opt/windchillAI/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable windchill-ai
sudo systemctl start windchill-ai
sudo systemctl status windchill-ai
```

---

## Architecture overview

```
Browser / Frontend / Postman
         │
         ▼ HTTP
┌─────────────────────────┐
│  FastAPI  (port 8000)   │
│  backend/main.py        │
│                         │
│  POST /api/v1/ask       │
│    1. embed query       │
│    2. search Qdrant     │──────► Qdrant (port 6333)
│    3. call Claude API   │──────► api.anthropic.com
│    4. return answer     │
└─────────────────────────┘
         ▲
         │ (index job — run manually or via cron)
┌─────────────────────────┐
│  sync_windchill.py      │──────► Windchill REST API
│  index_mock_data.py     │──────► mock_data/*.json
└─────────────────────────┘
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `invalid x-api-key` | Wrong or missing Anthropic key | Check `ANTHROPIC_API_KEY` in `.env` |
| `credit balance too low` | No Anthropic credits | Add credits at console.anthropic.com |
| `Connection refused :6333` | Qdrant not running | Run `docker-compose up -d qdrant` |
| `No relevant PLM data found` | Qdrant collection empty | Run the index/sync script first |
| `TypeError: unsupported operand type \|` | Python < 3.10 | Already fixed in this codebase |
| `SSL verification failed` | Self-signed cert on Windchill | Set `WINDCHILL_SSL_VERIFY=false` in `.env` |
| `401 from Windchill` | Bad credentials | Check `WINDCHILL_USERNAME` / `WINDCHILL_PASSWORD` |
| `404 from Windchill` | Wrong endpoint path | Update `WINDCHILL_*_PATH` vars to match your version |

---

## Air-gapped installation (no internet on server)

If the server cannot reach the internet, download the embedding model on a machine that can:

```bash
# On your Mac (inside the project venv)
python3 -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
m.save('./embedding_model')
"

# Copy the model folder to the server
rsync -av ./embedding_model/ user@server:/opt/windchillAI/embedding_model/
```

Then in `.env` on the server:

```dotenv
EMBED_MODEL=./embedding_model
```
