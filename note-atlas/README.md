# Note Atlas

Local-first personal knowledge app. Ingest notes, extract topics with a local LLM, search them, map them, and ask questions — all on your machine. Nothing leaves localhost except the optional Hugging Face download of the embedding weights the first time they are missing from the sentence-transformers cache.

## Prerequisites

- Python 3.11+ (3.12 used in development)
- Node.js 18+ and [pnpm](https://pnpm.io/)
- [Ollama](https://ollama.com/) running locally

No cloud APIs, accounts, or telemetry. Keep `OLLAMA_HOST` on loopback.

## Environment

From this directory:

```bash
cp .env.example .env
```

`.env.example` keys:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Local Ollama HTTP API |
| `OLLAMA_MODEL` | `qwen2.5:3b-instruct` | Chat, extraction, and Ask |
| `EMBED_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model for search/Ask |
| `DB_PATH` | `./data/notes.db` | SQLite + sqlite-vec file (resolved from this directory) |

## Swap the local models

Chat / extraction / Ask all go through `backend/app/llm.py`. Point `OLLAMA_MODEL` at any instruct model already pulled in Ollama, for example:

```bash
ollama pull qwen3:4b
OLLAMA_MODEL=qwen3:4b uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Vector search uses `sentence-transformers` via `backend/app/embed.py`. Change `EMBED_MODEL` to another MiniLM-class model with **384 dimensions** (the sqlite-vec table is created at that width). After changing it, run `POST /reindex` so existing chunks match the new vectors. A different embedding dimension needs a schema bump — do not mix sizes in one `notes.db`.

## Ollama

Start the daemon, then pull the default model (or whichever you set in `.env`):

```bash
ollama serve
ollama pull qwen2.5:3b-instruct
```

## Offline workflow

1. **Backend** — install once, then run with no network except Ollama on localhost:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

2. **Frontend** — in a second terminal:

```bash
cd frontend
pnpm install
pnpm dev
```

3. Open [http://localhost:5173](http://localhost:5173).

4. **Capture** a note → **Extract** topics (local LLM) → browse **Repository** (all notes) and **Map** (note hubs + optional shared-tag links) → **Ask** questions grounded in your notes.

5. **Export** a note as JSON or Markdown from Capture; **Import** the file back to create a copy with its extraction intact.

Checks:

- `GET http://127.0.0.1:8000/health` → `{"status":"ok"}`
- `GET http://127.0.0.1:8000/llm/ping` → `reachable: true` when Ollama is up
- UI pills: `backend = ok`, `model = reachable`

The UI calls `http://127.0.0.1:8000` (override with `VITE_API_BASE` if needed).

Theme defaults to the OS light/dark preference; the header control cycles System → Light → Dark. Keyboard focus uses a visible ring; the map and repository respect `prefers-reduced-motion`.
