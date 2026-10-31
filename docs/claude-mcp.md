# Use Atlas from Claude (MCP)

`backend/mcp_server.py` is a local MCP server that lets Claude read your Boards and notes, ask
them, and add notes. It is a thin stdio bridge over the Atlas HTTP API, so **the backend must be
running** (`uvicorn app.main:app --port 8888 --reload` in `backend/`). It stays on your machine:
Claude Code and Claude Desktop launch it locally; claude.ai in a browser can't reach it.

| Tool | What it does | Atlas endpoint |
|---|---|---|
| `list_boards` | Boards with domain description and counts | `GET /boards` |
| `list_notes(board?)` | Note titles on one Board or all | `GET /notes` |
| `get_note(note_id)` | One note's raw text, topics and points | `GET /notes/{id}` |
| `search(query, board?, k?)` | Best-matching passages with note titles | `GET /search` |
| `ask(question, board?, note_ids?, k?)` | Atlas's own RAG answer (Ollama) with citations | `POST /ask` |
| `create_note(title, raw_text, source?, board?)` | Add a note; extraction runs in the background | `POST /notes` |

`board` takes a Board's name, slug or id. Every tool except `create_note` is marked read-only.
Set `ATLAS_URL` to point at a backend on another address (default `http://127.0.0.1:8888`).

## Setup

Install the SDK into the backend venv once:

```bash
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

### Claude Code

From the repo root:

```bash
claude mcp add atlas --scope local -- "$PWD/backend/.venv/bin/python" "$PWD/backend/mcp_server.py"
```

Check it with `claude mcp get atlas` (should say Connected).

### Claude Desktop

Add an `mcpServers` entry to `~/Library/Application Support/Claude/claude_desktop_config.json`
(Settings → Developer → Edit Config), keeping whatever else is in the file, then fully quit and
reopen Claude Desktop:

```json
{
  "mcpServers": {
    "atlas": {
      "command": "/Users/klinthjeraldmatugas/Documents/DEV/ATLAS/backend/.venv/bin/python",
      "args": ["/Users/klinthjeraldmatugas/Documents/DEV/ATLAS/backend/mcp_server.py"]
    }
  }
}
```

Desktop doesn't set a working directory, which is why both paths are absolute and the server
imports nothing from `app`.

## Try it

- "What Boards do I have in Atlas?"
- "Search my Thesis Board for what I wrote about PII detection."
- "Ask Atlas: how does my notes app chunk text?" (uses the local LLM, so it's slower)
- "Add a note to Thesis titled 'Reviewer feedback' with: …"
