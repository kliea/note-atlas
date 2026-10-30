"""The Files pipeline: plain document Q&A over folders of uploaded files (the lab RAG stack).

Isolated from the Board and Research pipelines: it shares only the Ollama client and the
config loader, and its vectors live only in ChromaDB. Importable without FastAPI running,
because the Streamlit lab app calls it directly.
"""
