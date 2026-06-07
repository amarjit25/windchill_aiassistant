# Ollama Setup Guide — Local LLM for Windchill AI Assistant

Use this guide when your organization cannot access the Anthropic API
(no internet, corporate firewall, or data privacy requirements).

Ollama runs open-source LLMs entirely on your own server.
No API key. No internet after install. Data never leaves your network.

---

## How it fits into the system

```
User Question
     │
     ▼
FastAPI  /api/v1/ask
     │
     ▼  (LLM_PROVIDER=ollama)
rag_chain.py
     ├── Qdrant  ← semantic search (unchanged)
     └── Ollama  ← answer generation  ← replaces Anthropic API
          │
          ▼
     Local model (llama3.1 / mistral / qwen2.5 etc.)
     Running on your server, port 11434
```

The only thing that changes compared to the Claude setup is the last step.
Qdrant, the embedding model, and the FastAPI app all work identically.

---

## Step 1 — Install Ollama on the server

### Linux (recommended for production)

```bash
curl -fsSL https://ollama.com/install.sh | sh

# Verify
ollama --version
```

Ollama installs as a systemd service and starts automatically on boot.

### macOS (for local dev)

```bash
# Download from https://ollama.com and install the .dmg
# Or via Homebrew:
brew install ollama
ollama serve   # starts the server on port 11434
```

### Windows

Download the installer from https://ollama.com — it runs as a background service.

---

## Step 2 — Pull a model

Choose one based on your server's hardware:

| Model | Command | RAM needed | Best for |
|---|---|---|---|
| `llama3.1` | `ollama pull llama3.1` | 8 GB | Best quality, recommended |
| `llama3.2` | `ollama pull llama3.2` | 4 GB | Smaller, faster |
| `mistral` | `ollama pull mistral` | 6 GB | Good for structured data |
| `qwen2.5` | `ollama pull qwen2.5` | 6 GB | Strong multilingual |
| `phi3` | `ollama pull phi3` | 4 GB | Lightweight, low RAM |

```bash
# Pull the recommended model
ollama pull llama3.1

# Verify it downloaded
ollama list
```

Expected output:
```
NAME            ID              SIZE    MODIFIED
llama3.1:latest 42182419e950    4.7 GB  2 minutes ago
```

---

## Step 3 — Verify Ollama is running

```bash
# Check the Ollama server is up
curl http://localhost:11434/api/tags

# Expected: JSON list of downloaded models
# {"models":[{"name":"llama3.1:latest",...}]}
```

If it is not running:
```bash
# Linux
sudo systemctl start ollama
sudo systemctl status ollama

# macOS
ollama serve
```

---

## Step 4 — Configure the application

Open `.env` in the project root and make these two changes:

```dotenv
# Switch from Claude to Ollama
LLM_PROVIDER=ollama

# Point to your Ollama server
# If Ollama runs on the same machine as the app:
OLLAMA_BASE_URL=http://localhost:11434

# If Ollama runs on a different server:
OLLAMA_BASE_URL=http://192.168.1.100:11434

# Model you pulled in Step 2
OLLAMA_MODEL=llama3.1
```

You do NOT need to set or change `ANTHROPIC_API_KEY` when using Ollama.

---

## Step 5 — Start the application

Everything else is the same as the standard setup:

```bash
# 1. Start Qdrant (if not already running)
docker-compose up -d qdrant

# 2. Index data (if not already indexed)
source .venv/bin/activate
python scripts/index_mock_data.py --recreate   # mock data
# or
python scripts/sync_windchill.py --full        # live Windchill

# 3. Start the API
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Step 6 — Test it

```bash
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "What material is the engine frame made of?"}' \
  | python3 -m json.tool
```

The response `model` field will confirm which provider answered:

```json
{
  "answer": "The engine frame (ENG-FRAME-001) is made of Ti-6Al-4V...",
  "model": "ollama/llama3.1",
  "usage": {
    "input_tokens": 412,
    "output_tokens": 89
  }
}
```

When using Claude it shows `claude-haiku-4-5`. When using Ollama it shows `ollama/llama3.1`.

---

## Switching between Claude and Ollama

No code changes needed — just change one line in `.env` and restart uvicorn:

```dotenv
# Use Claude (Anthropic API)
LLM_PROVIDER=claude

# Use Ollama (local)
LLM_PROVIDER=ollama
```

---

## Running Ollama on a separate server (recommended for production)

If you want Ollama on a dedicated GPU server and the FastAPI app on a different machine:

**On the Ollama server:**
```bash
# Allow connections from other machines (default only listens on localhost)
OLLAMA_HOST=0.0.0.0 ollama serve

# Or set it permanently in the systemd service:
sudo systemctl edit ollama
```

Add under `[Service]`:
```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

**On the FastAPI server** — update `.env`:
```dotenv
OLLAMA_BASE_URL=http://<ollama-server-ip>:11434
```

Make sure port 11434 is open in the firewall between the two servers.

---

## Air-gapped installation (no internet on the server)

If the server has no internet access at all, download the model on a machine that does
and copy it across.

**On a machine with internet:**
```bash
ollama pull llama3.1

# Find where Ollama stores models
# Linux: ~/.ollama/models
# macOS: ~/.ollama/models
ls ~/.ollama/models
```

**Copy to the air-gapped server:**
```bash
rsync -av ~/.ollama/models/ user@air-gapped-server:~/.ollama/models/
```

**On the air-gapped server:**
```bash
ollama list   # should show llama3.1 without any download
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `Cannot reach Ollama at http://localhost:11434` | Ollama not running | Run `ollama serve` or `systemctl start ollama` |
| `Model 'llama3.1' not found` | Model not pulled | Run `ollama pull llama3.1` |
| Response is slow (30–60s) | No GPU, running on CPU | Normal for CPU; use a smaller model like `phi3` |
| `connection refused` from remote server | Ollama bound to localhost | Set `OLLAMA_HOST=0.0.0.0` on the Ollama server |
| Answer quality is poor | Small model, complex query | Switch to `llama3.1` (8B) or `qwen2.5` |
| `ANTHROPIC_API_KEY is not set` | Old validate() ran | Confirm `LLM_PROVIDER=ollama` is saved in `.env` and uvicorn was restarted |

---

## Hardware recommendations

| Setup | Minimum | Recommended |
|---|---|---|
| CPU only (dev/testing) | 8 GB RAM | 16 GB RAM |
| GPU (production) | 6 GB VRAM (RTX 3060) | 16 GB VRAM (RTX 4080) |
| Response time CPU | 30–90 seconds | — |
| Response time GPU | 2–5 seconds | — |

For production use, a GPU is strongly recommended.
`llama3.1` on an RTX 3060 answers in 2–4 seconds.
`llama3.1` on CPU (16 GB RAM) answers in 45–90 seconds.
