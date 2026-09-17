import { useCallback, useEffect, useState } from "react";
import {
  createNote,
  downloadNoteExport,
  extractNote,
  fetchHealth,
  fetchLlmPing,
  fetchNote,
  fetchNotes,
  importNoteFile,
} from "./api";
import { AskView } from "./components/AskView";
import { BoardView } from "./components/BoardView";
import { CaptureForm } from "./components/CaptureForm";
import { MapView } from "./components/MapView";
import { NoteList } from "./components/NoteList";
import { Repository } from "./components/Repository";
import { StatusPills } from "./components/StatusPills";
import { ThemeToggle } from "./components/ThemeToggle";
import { ViewNav } from "./components/ViewNav";
import { useHashView } from "./hooks/useHashView";
import { useTheme } from "./hooks/useTheme";
import type { Citation, NoteSummary, PillState, Topic } from "./types";

export default function App() {
  const { pref, resolved, cycle } = useTheme();
  const [view, setView] = useHashView();
  const [backend, setBackend] = useState<PillState>("loading");
  const [model, setModel] = useState<PillState>("loading");
  const [modelName, setModelName] = useState<string | null>(null);

  const [notes, setNotes] = useState<NoteSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");
  const [rawText, setRawText] = useState("");
  const [topics, setTopics] = useState<Topic[]>([]);
  const [saving, setSaving] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTopicId, setSelectedTopicId] = useState<number | null>(null);
  const [repoNoteId, setRepoNoteId] = useState<number | null>(null);

  useEffect(() => {
    void fetchHealth()
      .then((data) => {
        setBackend(data.status === "ok" ? "ok" : "error");
      })
      .catch(() => {
        setBackend("error");
      });

    void fetchLlmPing()
      .then((data) => {
        setModel(data.reachable ? "ok" : "error");
        setModelName(data.model);
      })
      .catch(() => {
        setModel("error");
      });
  }, []);

  const refreshNotes = useCallback(async (): Promise<NoteSummary[]> => {
    const listed = await fetchNotes();
    setNotes(listed);
    return listed;
  }, []);

  useEffect(() => {
    void refreshNotes().catch(() => {
      setError("Could not load notes.");
    });
  }, [refreshNotes]);

  function clearForm(): void {
    setSelectedId(null);
    setTitle("");
    setSource("");
    setRawText("");
    setTopics([]);
    setError(null);
  }

  async function handleSelect(id: number): Promise<void> {
    setError(null);
    try {
      const note = await fetchNote(id);
      setSelectedId(note.id);
      setTitle(note.title);
      setSource(note.source);
      setRawText(note.raw_text);
      setTopics(note.topics);
    } catch {
      setError("Could not open that note.");
    }
  }

  async function handleSave(): Promise<void> {
    setSaving(true);
    setError(null);
    try {
      const saved = await createNote({
        title: title.trim(),
        source: source.trim(),
        raw_text: rawText,
      });
      await refreshNotes();
      setSelectedId(saved.id);
      setTitle(saved.title);
      setSource(saved.source);
      setRawText(saved.raw_text);
      setTopics(saved.topics);
    } catch {
      setError("Save failed. Is the backend running?");
    } finally {
      setSaving(false);
    }
  }

  async function handleExtract(): Promise<void> {
    if (selectedId === null) {
      return;
    }
    setExtracting(true);
    setError(null);
    try {
      const updated = await extractNote(selectedId);
      setTopics(updated.topics);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Extraction failed.";
      setError(message);
    } finally {
      setExtracting(false);
    }
  }

  async function handleExport(format: "json" | "markdown"): Promise<void> {
    if (selectedId === null) {
      return;
    }
    setError(null);
    try {
      await downloadNoteExport(selectedId, format);
    } catch {
      setError("Export failed.");
    }
  }

  async function handleImport(file: File): Promise<void> {
    setImporting(true);
    setError(null);
    try {
      const imported = await importNoteFile(file);
      await refreshNotes();
      setSelectedId(imported.id);
      setTitle(imported.title);
      setSource(imported.source);
      setRawText(imported.raw_text);
      setTopics(imported.topics);
      setView("capture");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Import failed.";
      setError(message);
    } finally {
      setImporting(false);
    }
  }

  function handleAskSource(citation: Citation): void {
    void handleSelect(citation.note_id);
    if (citation.topic_id !== null) {
      setSelectedTopicId(citation.topic_id);
      setRepoNoteId(citation.note_id);
      setView("repository");
    } else {
      setView("capture");
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <h1>Note Atlas</h1>
          <p className="lede">Capture notes, extract topics, map them.</p>
        </div>
        <ViewNav view={view} onChange={setView} />
        <div className="topbar-tools">
          <ThemeToggle pref={pref} onCycle={cycle} />
          <StatusPills backend={backend} model={model} modelName={modelName} />
        </div>
      </header>
      {view === "capture" ? (
        <div className="workspace">
          <NoteList
            notes={notes}
            selectedId={selectedId}
            onSelect={(id) => {
              void handleSelect(id);
            }}
            onNew={clearForm}
          />
          <CaptureForm
            title={title}
            source={source}
            rawText={rawText}
            saving={saving}
            extracting={extracting}
            importing={importing}
            canExtract={selectedId !== null}
            topics={topics}
            error={error}
            onTitleChange={setTitle}
            onSourceChange={setSource}
            onRawTextChange={setRawText}
            onSubmit={() => {
              void handleSave();
            }}
            onExtract={() => {
              void handleExtract();
            }}
            onExport={(format) => {
              void handleExport(format);
            }}
            onImportFile={(file) => {
              void handleImport(file);
            }}
          />
        </div>
      ) : null}
      {view === "repository" ? (
        <Repository
          notes={notes}
          selectedTopicId={selectedTopicId}
          focusedNoteId={repoNoteId}
          onSelectTopic={setSelectedTopicId}
        />
      ) : null}
      {view === "map" ? (
        <MapView
          notes={notes}
          selectedTopicId={selectedTopicId}
          colorMode={resolved}
          onSelectTopic={(topicId, noteId) => {
            setSelectedTopicId(topicId);
            setRepoNoteId(noteId);
          }}
          onSelectNote={(noteId) => {
            setRepoNoteId(noteId);
            void handleSelect(noteId);
            setView("repository");
          }}
          onFocusCard={() => setView("repository")}
        />
      ) : null}
      {view === "ask" ? <AskView onSelectSource={handleAskSource} /> : null}
      {view === "board" ? <BoardView /> : null}
    </div>
  );
}
