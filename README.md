# Note Atlas

Local-first spatial notebook. Capture a thought on the canvas; on save a local LLM rephrases the jot into a clearer note, extracts topics, and related notes offer a faint string you can accept. Ask with a lasso. Nothing leaves localhost except the optional first-time download of embedding weights into the sentence-transformers cache.

## Interaction model

The app opens on the **board**. There is no Capture / Repository / Map / Ask chrome.

- **Write** — double-click empty space, press `N`, tear off **New note**, or paste. First line is the title.
- **Polish** — after save, the local LLM rewrites the jot into a clearer note with implied detail, then extracts topics and tags. The card shimmers while that runs. Ask answers are left alone.
- **Link** — drag a handle, or select two notes and press `L`. Cut the bead on a string to disconnect. Suggested links appear as dashed ghosts; accept or dismiss.
- **Ask** — Shift-drag a cluster, then `/`. Tab to a note, Space to select, Shift-Space to add more, then `/`. With nothing selected, ask spans the whole board. The answer pins as a note with strings to cited sources. Off-topic questions are declined, not invented.
- **Undo** — ⌘Z / Ctrl+Z, depth 50.

## Gestures and shortcuts

| Input | Action |
| --- | --- |
| Double-click canvas | New note |
| `N` | New note at view center |
| Enter | Edit selected note |
| `Tab` | Move focus between notes and controls |
| `Space` | Select the focused note |
| `Shift-Space` | Add or remove the focused note from the selection |
| Esc | Close ask, shortcuts, or finish editing |
| Arrow keys | Nudge selected note (Shift = larger step, snapped to 24px) |
| Shift-drag | Lasso notes |
| ⌘/Ctrl-click | Add to selection |
| `L` | Link two selected notes |
| `R` | Re-fetch related links for the selection, or every note |
| `/` | Ask (scoped to the selection if any) |
| `?` | Shortcuts overlay |
| Backspace / Delete | Delete selected note |
| ⌘Z / Ctrl+Z | Undo |
| ⇧⌘Z / Ctrl+Shift+Z | Redo |
| Paste | Drop clipboard text as a note |
| Drag a `.json` / `.md` file onto the board | Import |

Visible focus uses a 2px accent ring (`:focus-visible`). `prefers-reduced-motion: reduce` turns fit/auto-pan into instant moves; CSS animations collapse. The canvas keeps `@xyflow/react` because the board still uses it; the retired Capture/Map/Ask/Repository screens and their CSS are gone.

## Prerequisites

- Python 3.11+ (3.12 used in development)
- Node.js 18+ and [pnpm](https://pnpm.io/)
- [Ollama](https://ollama.com/) running locally
- [Docker](https://www.docker.com/) for the Research Track's PDF parser (GROBID). Atlas starts the `grobid/grobid:0.9.1-crf` container on `127.0.0.1:8070` when you upload a paper and stops it after the queue has been idle for two minutes. It needs about 4 GB of RAM while running. Without Docker, uploads still work but keep only plain text, with no references.

No accounts or telemetry, and the board never leaves localhost. Keep `OLLAMA_HOST` on loopback.

The one exception is the Research Track's scholarly lookups. When it's on, the default, Atlas sends paper and reference **titles, DOIs, and OpenAlex ids** (never PDFs, extracted text, or notes) to [OpenAlex](https://openalex.org), and falls back to [Crossref](https://www.crossref.org) for references OpenAlex doesn't link. Switch it off with the status pill in the Research view; year, DOI, and links then come only from the PDF.

## Environment

From this directory:

```bash
cp .env.example .env
```

`.env.example` keys:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Local Ollama HTTP API |
| `OLLAMA_MODEL` | `qwen3:4b` | Chat, extraction, and Ask |
| `EMBED_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model for search/Ask |
| `DB_PATH` | `./data/notes.db` | SQLite + sqlite-vec file (resolved from this directory); uploaded papers go in `papers/` next to it |
| `GROBID_URL` | `http://127.0.0.1:8070` | Local GROBID service for parsing papers |
| `GROBID_IMAGE` | `grobid/grobid:0.9.1-crf` | Image Atlas starts on demand |
| `GROBID_AUTOSTART` | `1` | Set to `0` to never start the container, e.g. if you run GROBID yourself |
| `OPENALEX_API_KEY` | _(blank)_ | Optional free key; raises OpenAlex's daily budget from $0.10 to $1. A paper cost about $0.001 in testing, so the keyless budget covers dozens a day |
| `S2_API_KEY` | _(blank)_ | Optional Semantic Scholar key of your own, for influence signals when ranking Parent Papers |
| `CROSSREF_MAILTO` | _(blank)_ | Optional email for Crossref's faster "polite" pool; blank by default because it identifies you |

## Offline run

1. **Ollama**

```bash
ollama serve
ollama pull qwen3:4b
# or: ollama pull qwen3:4b
```

2. **Backend** — install once, then run with no network except Ollama on localhost:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload --host 127.0.0.1 --port 8888
```

3. **Frontend** — in a second terminal:

```bash
cd frontend
pnpm install
pnpm dev
```

4. Open [http://localhost:5252](http://localhost:5252). You land on the canvas.

5. Write a jot and leave the card. It is rewritten into a fuller note, then topics appear. Ask with `/`. Off-topic questions return `I don't have that in the notes.`

Checks:

- `GET http://127.0.0.1:8888/health` → `{"status":"ok"}`
- `GET http://127.0.0.1:8888/llm/ping` → `reachable: true` when Ollama is up
- Header pills: `backend = ok`, `model = reachable`

The UI calls `http://127.0.0.1:8888` (override with `VITE_API_BASE` if needed).

Theme defaults to the OS light/dark preference; the header control cycles System → Light → Dark.

## Swap the local models

Chat / extraction / Ask all go through `backend/app/llm.py`. Point `OLLAMA_MODEL` at any instruct model already pulled in Ollama:

```bash
OLLAMA_MODEL=qwen3:4b uvicorn app.main:app --host 127.0.0.1 --port 8888
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
routing is gone; the app opens on the board. React Flow stays because
the board canvas uses it.
```

Do not squash if you still want the R1–R9 commits for archaeology; in that case merge with `--no-ff`.
