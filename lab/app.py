"""Simple RAG with Phi-3: the MSIT lab's Streamlit app, running on Note Atlas's Files pipeline.

Run from the repo root:  streamlit run lab/app.py   (then open http://localhost:8501)

Same database, same ChromaDB directory, and same models as the Files view in the React app;
the service layer is imported directly, so the FastAPI backend does not need to be running.
Don't build a knowledge base here and in the React app at the same time: ChromaDB's persistent
client is single-process.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.files import repo, service  # noqa: E402
from app.files.config import embed_model, llm_model, top_k  # noqa: E402
from app.files.embed import EmbeddingError  # noqa: E402
from app.files.models import RetrievedChunk  # noqa: E402
from app.llm import LlmError  # noqa: E402

ALL_FOLDERS = "All folders"
THIS_FOLDER = "This folder"

st.set_page_config(page_title="Simple RAG with Phi-3", layout="wide")
st.title("📚 Simple RAG Application using Phi-3")
st.caption(
    f"PyMuPDF · 500-character chunks · {embed_model()} embeddings · ChromaDB · "
    f"top-{top_k()} retrieval · {llm_model()} via Ollama"
)

service.init()

# ==================================================
# SESSION STATE
# ==================================================

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0
if "flash" not in st.session_state:
    st.session_state.flash = []  # (kind, message) shown once after a rerun


def flash(kind: str, message: str) -> None:
    st.session_state.flash.append((kind, message))


def chunk_label(index: int, chunk: RetrievedChunk) -> str:
    return f"Chunk {index} · {chunk.filename} · p.{chunk.page_start}"


# ==================================================
# SIDEBAR
# ==================================================

st.sidebar.header("Document Upload")

folders = service.list_folders()
with st.sidebar.expander("New folder", expanded=not folders):
    new_name = st.text_input("Folder name", key="new_folder_name", max_chars=100)
    if st.button("Create folder", disabled=not new_name.strip()):
        try:
            created = service.create_folder(new_name)
            st.session_state.folder_id = created.id
            flash("success", f"Folder “{created.name}” created.")
            st.rerun()
        except repo.FolderNameTaken:
            st.error(f"A folder named “{new_name.strip()}” already exists.")

folder = None
if folders:
    ids = [f.id for f in folders]
    if st.session_state.get("folder_id") not in ids:
        st.session_state.folder_id = ids[0]
    selected_id = st.sidebar.selectbox(
        "Folder",
        ids,
        key="folder_id",
        format_func=lambda folder_id: next(f.name for f in folders if f.id == folder_id),
    )
    folder = next(f for f in folders if f.id == selected_id)

st.sidebar.subheader("Knowledge Base Status")
status = service.index_status()
st.sidebar.write(f"Stored Chunks: {status.total_chunks}")
if folder is not None:
    st.sidebar.caption(f"In “{folder.name}”: {folder.chunk_count} chunks from {folder.document_count} files")

for kind, message in st.session_state.flash:
    getattr(st.sidebar, kind)(message)
st.session_state.flash = []

if folder is None:
    st.sidebar.info("Create a folder to start uploading documents.")
else:
    uploaded_files = st.sidebar.file_uploader(
        "Upload PDF Documents",
        type=["pdf", "txt"],
        accept_multiple_files=True,
        key=f"uploader-{st.session_state.uploader_key}",
    )

    if st.sidebar.button("Build Knowledge Base"):
        if uploaded_files:
            try:
                result = service.add_files(folder.id, [(f.name, f.getvalue()) for f in uploaded_files])
            except (repo.UnsupportedFile, repo.UploadTooLarge) as exc:
                st.sidebar.error(str(exc))
                st.stop()
            for skipped in result.skipped:
                flash("info", f"Skipped {skipped.filename} ({skipped.reason}).")
        progress = st.sidebar.progress(0.0, text="Processing documents...")

        def on_progress(done: int, total: int, document: object) -> None:
            name = getattr(document, "filename", "")
            progress.progress(done / total, text=f"Processing documents... {done}/{total} {name}")

        summary = service.build_folder(folder.id, on_progress=on_progress)
        flash("success", f"{summary.chunks} chunks indexed.")
        flash("caption", f"{summary.indexed} files indexed, {summary.skipped} already up to date, {summary.failed} failed.")
        for document in service.list_documents(folder.id):
            if document.status == "failed":
                flash("warning", f"{document.filename}: {document.error}")
        st.session_state.uploader_key += 1  # empty the uploader; files now live in the folder
        st.rerun()

    if st.sidebar.button("Clear Knowledge Base"):
        try:
            service.clear_folder_index(folder.id)
            flash("success", f"Knowledge base cleared for “{folder.name}”.")
        except service.BuildInProgress:
            flash("warning", "This folder is being indexed; try again when it finishes.")
        st.rerun()

    documents = service.list_documents(folder.id)
    if documents:
        with st.sidebar.expander(f"Files in “{folder.name}” ({len(documents)})"):
            for document in documents:
                pages = f"{document.page_count} pages · " if document.page_count else ""
                st.markdown(f"**{document.filename}**  \n{pages}{document.chunk_count} chunks · {document.status}")

# ==================================================
# MAIN UI
# ==================================================

st.header("Ask Questions")

scope = st.radio(
    "Search in",
    [THIS_FOLDER, ALL_FOLDERS] if folder is not None else [ALL_FOLDERS],
    horizontal=True,
    format_func=lambda s: f"{s} ({folder.name})" if s == THIS_FOLDER and folder is not None else s,
)
question = st.text_input("Enter your question")

if st.button("Ask") and question.strip():
    folder_ids = [folder.id] if scope == THIS_FOLDER and folder is not None else None
    try:
        with st.spinner("Searching documents..."):
            plan = service.plan_ask(question, folder_ids)
        if plan.empty_message is not None:
            st.info(plan.empty_message)
        else:
            st.subheader("Answer")
            answer = st.write_stream(service.stream_answer(plan))
            service.record_ask(plan, answer if isinstance(answer, str) else "".join(map(str, answer)))
            st.caption(f"Retrieved {len(plan.chunks)} chunks.")
            st.subheader("Retrieved Context")
            for i, chunk in enumerate(plan.chunks, start=1):
                with st.expander(chunk_label(i, chunk)):
                    st.caption(f"score {chunk.score:.2f}")
                    st.write(chunk.text)
    except EmbeddingError as exc:
        st.error(str(exc))
    except LlmError as exc:
        st.error(f"Ollama could not answer ({exc}). Is `ollama serve` running and `{llm_model()}` pulled?")

# ==================================================
# CHAT HISTORY
# ==================================================

history = service.chat_history()
if history:
    st.subheader("Chat History")
    for item in history:
        st.markdown(f"**Question:** {item.question}")
        st.markdown(f"**Answer:** {item.answer}")
        sources = "; ".join(dict.fromkeys(f"{c.filename} · p.{c.page_start}" for c in item.chunks))
        st.caption(f"{item.model}" + (f" · Sources: {sources}" if sources else ""))
        st.divider()
