# Note Atlas

Local-first spatial notebook. Capture a thought on the canvas; a local LLM extracts topics in the background; related notes offer a faint string you can accept. Ask with a lasso. Nothing leaves localhost except the optional first-time download of embedding weights into the sentence-transformers cache.

## Interaction model

The app opens on the **board**. There is no Capture / Repository / Map / Ask chrome.

- **Write** — double-click empty space, press `N`, tear off **New note**, or paste. First line is the title.
- **Extract** — happens in the background after capture or a meaningful edit. The card shimmers, then gains points and tags. No Extract button.
- **Link** — drag a handle, or select two notes and press `L`. Cut the bead on a string to disconnect. Suggested links appear as dashed ghosts; accept or dismiss.
- **Ask** — Shift-drag a cluster, then `/`. With nothing lassoed, ask spans the whole board. The answer pins as a note with strings to cited sources. Off-topic questions are declined, not invented.
- **Undo** — ⌘Z / Ctrl+Z, depth 50.

## Gestures and shortcuts

| Input | Action |
| --- | --- |
| Double-click canvas | New note |
| `N` | New note at view center |
| Enter | Edit selected note |
| Esc | Close ask, shortcuts, or finish editing |
| Arrow keys | Nudge selected note (Shift = larger step, snapped to 24px) |
| Shift-drag | Lasso notes |
| Shift-click | Add to selection |
| `L` | Link two selected notes |
| `/` | Ask (scoped to the lasso if any) |
| `?` | Shortcuts overlay |
| Backspace / Delete | Delete selected note |
| ⌘Z / Ctrl+Z | Undo |
| ⇧⌘Z / Ctrl+Shift+Z | Redo |
| Paste | Drop clipboard text as a note |
| Drag a `.json` / `.md` file onto the board | Import |

Visible focus uses a 2px accent ring (`:focus-visible`). `prefers-reduced-motion: reduce` turns fit/auto-pan into instant moves; CSS animations collapse.

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

## Offline run

1. **Ollama**

```bash
ollama serve
ollama pull qwen2.5:3b-instruct
# or: ollama pull qwen3:4b
```

2. **Backend** — install once, then run with no network except Ollama on localhost:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

3. **Frontend** — in a second terminal:

```bash
cd frontend
pnpm install
pnpm dev
```

4. Open [http://localhost:5173](http://localhost:5173). You land on the canvas.

5. Write a note. Topics appear shortly after with nothing pressed. Ask with `/`. Off-topic questions return `I don't have that in the notes.`

Checks:

- `GET http://127.0.0.1:8000/health` → `{"status":"ok"}`
- `GET http://127.0.0.1:8000/llm/ping` → `reachable: true` when Ollama is up
- Header pills: `backend = ok`, `model = reachable`

The UI calls `http://127.0.0.1:8000` (override with `VITE_API_BASE` if needed).

Theme defaults to the OS light/dark preference; the header control cycles System → Light → Dark.

## Swap the local models

Chat / extraction / Ask all go through `backend/app/llm.py`. Point `OLLAMA_MODEL` at any instruct model already pulled in Ollama:

```bash
OLLAMA_MODEL=qwen3:4b uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Vector search uses `sentence-transformers` via `backend/app/embed.py`. Change `EMBED_MODEL` to another MiniLM-class model with **384 dimensions**. After changing it, run `POST /reindex`. A different embedding dimension needs a schema bump — do not mix sizes in one `notes.db`.

## Squash-merge notes (`refactor/nui-board` → `main`)

This branch is a strangler-fig cutover (R1–R7, R8 skipped, R9). Prefer a **squash merge** onto `main` so the public history is one commit, not the intermediate board-behind-a-hash steps.

Suggested squash message:

```
Replace the Capture/Map/Ask chrome with a spatial board.

Notes live on a canvas: one-gesture capture, background extraction,
drag-to-link strings, lasso-scoped Ask, and keyboard shortcuts.
Schema stays additive (v3 space, v4 extract_status). Old view hash
routing is gone; the app opens on the board.
```

Do not squash if you still want the R1–R9 commits for archaeology; in that case merge with `--no-ff`.
