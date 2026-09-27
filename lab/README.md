# Simple RAG with Phi-3: MSIT lab app

The laboratory exercise *Building a Simple RAG Application using Streamlit, ChromaDB, Ollama,
and Phi-3*, running on Note Atlas's **Files** pipeline. `lab/app.py` is a Streamlit shell that
imports the pipeline's service layer (`backend/app/files/service.py`) directly, so the FastAPI
backend does not need to be running.

It shares the React app's database, ChromaDB directory, and models: a folder built here is
visible in Note Atlas's **Files** view, and Chat History is the same list in both.

## Setup (mirrors the lab handout)

**Part 1. Software.** Python 3.11 or newer, and [Ollama](https://ollama.com/download).

```bash
python --version        # 3.11+
ollama --version
```

**Part 2. Models.**

```bash
ollama pull phi3
ollama pull nomic-embed-text
ollama list             # both should be listed
```

**Parts 4–5. Virtual environment and libraries.** From the repo root:

```bash
python -m venv .venv-lab
source .venv-lab/bin/activate          # Windows: .venv-lab\Scripts\activate
pip install -r lab/requirements.txt
```

(If you already use `backend/.venv` for Note Atlas, `pip install -r lab/requirements.txt` into
it instead; the versions are compatible.)

**Part 8. Start Ollama** and keep that terminal open:

```bash
ollama serve
```

**Part 9. Run the app** from the repo root:

```bash
streamlit run lab/app.py
```

Open <http://localhost:8501>.

**Part 10. Test it.**

1. In the sidebar, create a folder (for example *Lectures*).
2. Upload one or more PDFs or `.txt` files and click **Build Knowledge Base**. The progress bar
   shows each file; **Stored Chunks** updates when it finishes.
3. Ask questions such as *What methodology was used in the study?* The answer streams in, then
   **Retrieved N chunks.** and one **Retrieved Context** expander per chunk (file name and page).
4. Ask something the documents don't cover. The answer should be exactly:
   `The information is not available in the uploaded documents.`
5. **Clear Knowledge Base** removes the selected folder's vectors (its files stay, ready to build
   again).

## Do not build from both apps at once

ChromaDB's persistent client is single-process. Asking from both apps at once is fine, but don't
build or clear a knowledge base here while the Note Atlas backend is building one (or the other
way round). If you need to, stop one of them first.

## Where each lab function lives

| Lab (Part 6) | What it does | Files pipeline |
|---|---|---|
| `extract_text` | PyMuPDF, `page.get_text()` per page | `backend/app/files/extract.py` → `extract_text` |
| `chunk_text` | fixed 500-character chunks | `backend/app/files/chunk.py` → `chunk_text`, `chunk_pages` |
| `create_embedding` | Ollama `nomic-embed-text` | `backend/app/files/embed.py` → `embed_texts` (via `app.llm.embed`, `/api/embed`) |
| `add_to_vector_db` | ChromaDB persistent collection | `backend/app/files/store.py` → `upsert_chunks`; `build.py` → `build_folder` |
| `retrieve_context` | similarity search, top-k 3 | `backend/app/files/retrieve.py` → `retrieve_context` |
| `generate_answer` | Phi-3, answer ONLY from context | `backend/app/files/answer.py` → `build_prompt`, `stream_answer` |
| Knowledge Base Status / Build / Clear | sidebar | `service.index_status`, `service.build_folder`, `service.clear_folder_index` |
| Chat History | `st.session_state.history` | `file_asks` table (`service.chat_history`), persists across restarts |

### Differences from the handout code, and why

- **Folders.** Documents live in named folders; you ask one folder or all of them.
- **Stable chunk ids** (`"{document_id}:{chunk_idx}"`, written with upsert) instead of random
  UUIDs, so clicking **Build Knowledge Base** twice doesn't store every chunk twice.
- **Uploads are kept** (under `data/files/`), so building again only processes new files.
- **Sources.** Each retrieved chunk shows its file name and the page it starts on.
- **`.txt` and `.docx` files** are accepted as well as PDFs (enhancement activities 1 and 2).
- `import pymupdf` instead of `import fitz`: it's the same library, and `fitz` now prints a
  deprecation warning.
- The `ollama` Python package isn't needed; Note Atlas calls Ollama's HTTP API.

## Settings

Set in the repo's `.env` (see `.env.example`) or the shell:

| Variable | Default | |
|---|---|---|
| `FILES_EMBED_MODEL` | `nomic-embed-text` | embedding model |
| `FILES_LLM_MODEL` | `phi3` | answer model |
| `FILES_TOP_K` | `3` | chunks retrieved per question |
| `FILES_CHUNK_SIZE` / `FILES_CHUNK_OVERLAP` | `500` / `0` | chunking (Clear, then Build, after changing) |
| `FILES_SCORE_THRESHOLD` | blank (off) | minimum similarity; below it, refuse without calling the model |
| `FILES_CHROMA_PATH` | `./data/chroma_files` | ChromaDB directory |
| `FILES_DIR` | `./data/files` | stored uploads |
| `DB_PATH` | `./data/notes.db` | shared SQLite database |

## Enhancement activities

Each one has its own switch in `.env`. The first four in the table add inputs or display and are
on by default; hybrid search and memory change what the model sees, so they're off by default.
With everything at its default, a PDF question answered by `phi3` goes through exactly the lab's
pipeline and prompt.

| # | Enhancement | Switch (default) | What it does |
|---|---|---|---|
| 1 | Word (.docx) | `FILES_DOCX=1` | Paragraphs and tables (one row per line, cells joined by ` \| `) in document order. **A .docx is one page**: Word has no fixed pagination to recover, so chunks report `p.1` rather than invented page numbers. |
| 2 | Text (.txt) | `FILES_TXT_FALLBACK=1` | A file that isn't UTF-8 is read as Windows-1252 instead of rejected; the encoding used is shown next to the file name. A UTF-8 byte-order mark is dropped. |
| 3 | Document names | `FILES_SHOW_SOURCES=1` | Every retrieved chunk shows `filename · p.N` (always), and each answer gets a **Sources** line. The line is left off when the answer is the refusal. |
| 4 | Hybrid search | `FILES_HYBRID=0` | BM25 keyword search over the same chunks, fused with vector search by Reciprocal Rank Fusion (k = 60). Each chunk says which search found it: vector, keyword (BM25), or both. The score shown stays the cosine similarity. |
| 5 | Conversational memory | `FILES_MEMORY_TURNS=0` | The last N questions and answers asked in the same scope go into the prompt in their own section, before the context. The prompt still says every fact must come from the context. Retrieval searches with the previous question and answer (unless it was the refusal; answer trimmed to 300 characters) plus the new question, so a follow-up like *What path does it persist to?* finds what *it* refers to; the combined search is shown under the answer. The model still gets the question exactly as asked. |
| 6 | Larger local models | `FILES_MODEL_PICKER=1` | A **Model** picker listing the chat models pulled into Ollama (`ollama pull llama3`, `ollama pull mistral`, …). The model used is recorded on each Chat History row. |
| 7 | Multi-user deployment | none | Not built. |

## Troubleshooting (Part 11)

| Error | Fix |
|---|---|
| Ollama connection failed / "could not reach Ollama" | `ollama serve` |
| Model not found / "embedding model … is not pulled" | `ollama pull phi3` and `ollama pull nomic-embed-text` |
| No module named `chromadb` | `pip install chromadb` (or `pip install -r lab/requirements.txt`) |
| No module named `fitz` / `pymupdf` | `pip install pymupdf` |
| `streamlit`: command not found | `pip install streamlit`, or `python -m streamlit run lab/app.py` |
| A PDF shows **failed**: "no extractable text" | It's scanned (images only); OCR isn't supported. Use a PDF with a text layer. |
| Stored Chunks doesn't change after Build | Everything was already indexed; that's expected. |
