# Boards — implementation spec

Note Atlas grows from one canvas to many **Boards**. Each Board holds one domain of knowledge: its own Notes on its **canvas**, its own Files folders, and references to Studies from the global Library. Its **domain description** steers the local LLM. Ask, suggestions and Strings never leave the Board.

Vocabulary: [`CONTEXT.md`](../../CONTEXT.md). Key structural decision: [ADR 0002 — A Note belongs to exactly one Board](../adr/0002-a-note-belongs-to-one-board.md). Every decision below links the wayfinder ticket that holds its full reasoning; the map is [issue #25](https://github.com/kliea/note-atlas/issues/25).

## Principles

- **A Board is a sealed scope.** Ask, related-note suggestions and Strings stay inside one Board. There is no cross-Board Ask or search in v1.
- **Owned vs referenced.** A Board *owns* its Notes and Files folders (each belongs to exactly one Board) and *references* Studies (the Library stays global).
- **Today's app is the default Board.** After migration, everything lives in one ordinary Board with an empty domain description, and Atlas behaves exactly as before.
- **Your words are never rewritten.** The domain description steers topic extraction and enrichment only. A note's text is always the user's own.
- **Nothing is deleted behind your back.** Detaching a Study, cutting a String on move, and a source going missing all leave Notes and Citations in place. Only an explicit, confirmed Board delete removes content.

## Data model (migration v13 in `notes.db`)

Decision: [#28](https://github.com/kliea/note-atlas/issues/28), with retrieval facts from [#26](https://github.com/kliea/note-atlas/issues/26).

v13 assumes the Files pipeline's v12 (branch `feat/files-pipeline`) has landed first.

- **Board**: name (unique, case-insensitive), domain description (nullable text), slug for the URL, created_at, last_opened_at.
- **Note** gains `board_id` (not null after migration). Strings (`connections`) are only valid between two Notes on the same Board; moving Notes cuts any that would cross.
- **Files folder** gains `board_id`. Folder names become unique **per Board** (`UNIQUE (board_id, name)`), not globally.
- **Board source**: `(board_id, study_id)` join, added_at, and how it was added (`send`, `add`). It references a Study, not only a Paper. A referenced Lead starts feeding Board Ask once its PDF is uploaded.
- **Ask answer citations**: an answer Note stores typed Citations (`note | file | paper`, ids, page, quoted text, label at ask time) as data, not only as Strings. See [Citations](#citations).
- **Migration**: create one Board (name "General", empty description), and set every existing Note and Files folder to it. The research tables are untouched.
- **Retrieval scoping**: sqlite-vec `rowid IN (SELECT id FROM chunks WHERE note_id IN (SELECT id FROM notes WHERE board_id = ?))` pre-filter inside the KNN query. It is exact because it filters before top-k, and the Board id stays on `notes` alone, so a move never touches `chunk_vec`. A `board_id` metadata column on `chunk_vec` is the fallback, only if measured timing calls for it. The same pre-filter pattern already fixes selected-note Ask past 4096 chunks (PR #33).

## Board lifecycle

Decisions: [#28](https://github.com/kliea/note-atlas/issues/28), [#30](https://github.com/kliea/note-atlas/issues/30), [#34](https://github.com/kliea/note-atlas/issues/34).

- **Create**: one dialog with a name (required, unique) and an optional "What is this Board about?" field (the domain description). The new Board opens.
- **Rename / edit description**: from the Board's menu. Editing the description doesn't re-run anything on its own.
- **Delete**: confirm by typing the Board's name. The dialog names the counts ("40 notes, 2 folders (17 files)") and says referenced Papers stay in the Library. Deletes the Board's Notes, Strings, Files folders and their documents and vectors. Not undoable. **The last Board can't be deleted.**
- **Move Notes**: select Notes on the canvas, then "Move to…", then pick a Board.
  - Strings among the moved Notes stay. Strings to Notes left behind are cut, and the dialog warns with the count.
  - You stay on the current Board, and a toast offers "Go to <Board>" and Undo (⌘Z restores the move and the cut Strings).
  - Each moved Note re-runs topic extraction and enrichment under the new Board's description. **Accepted** point context is kept on its point text. Suggested and dismissed context is regenerated.
- **Import**: a dropped `.json` / `.md` file lands in the Board you're on.

## Domain description and the LLM

Decision: [#29](https://github.com/kliea/note-atlas/issues/29) (read its correction comment: there is no polish step).

- **Topic extraction and enrichment** prepend a two-line preamble when the Board has a description, and nothing when it's empty:

  ```
  This note lives on a Board about: <description>
  Read ambiguous terms in that domain. Do not add facts that the text does not support.
  ```

- **Ask does not get the description** in v1. Board-scoped retrieval already keeps the context in the domain, and in the prototype a mismatched description caused a wrong "I don't have that in the notes".
- **Link suggestions** never call the LLM. The description reaches them only through the tags extraction produces.
- **Accepted risk**: an ambiguous note on the wrong Board gets topics, tags and suggested context from that Board's domain. The fix is moving it (above). Prototype: branch `prototype/domain-description`.

## UI

Decision: [#30](https://github.com/kliea/note-atlas/issues/30).

- **Header**: a Board dropdown (with "+ New board"), then `Canvas | Files` tabs that act inside the current Board. `Research` sits apart on the right, because the Library is global.
- **URL**: `?board=<slug>` plus `&view=files`. Research is `?view=research` with no Board. With no `?board=`, open the last-used Board, or the first Board if that one was deleted. Old `?view=files` links keep working (they open in the last-used Board).
- **Board menu**: rename, edit description, **Sources** (read-only list of referenced Studies, each with Remove), delete.
- **Research view**: "Add to Board…" on a Paper or Lead. "Send to board" (Claims and Research Ask answers) asks which Board, defaulting to the last-used one.

## Studies on a Board

Decisions: [#28](https://github.com/kliea/note-atlas/issues/28), [#35](https://github.com/kliea/note-atlas/issues/35).

- **Attach**:
  - "Add to Board…" from the Research view.
  - Sending a Claim to a Board adds its Paper.
  - Sending a Research Ask answer adds the Papers it cited.
- **Detach**: Remove in the Board's Sources list. Only future Board Asks stop drawing on it. Notes sent from it keep their Paper link, and stored Citations stay as snapshots.
- **Research Ask stays global** over the whole Library.

## Ask

Decisions: [#27](https://github.com/kliea/note-atlas/issues/27), [#32](https://github.com/kliea/note-atlas/issues/32).

**Phase 1 (Notes only).** Today's Ask, limited to the current Board's Notes through the pre-filter. A lasso or keyboard selection is already inside the Board. Off-topic questions are still declined when retrieval scores are weak, before the model runs. Files Ask keeps its own pipeline, limited to the Board's folders.

**Phase 2 (Notes + sources).** Board Ask also draws on the Board's Files folders and referenced Papers:

1. Retrieve 10–20 candidates per source from its own store: Notes (sqlite-vec), Files (Chroma, `folder_id` in the Board's folders), Papers (`research_vec`, Studies in the Board's sources).
2. Rerank all candidates together with a local cross-encoder (`cross-encoder/ms-marco-MiniLM-L6-v2` via sentence-transformers, in-process). This gives one score and one decline threshold.
3. qwen3:4b answers from the top 8–12, with numbered `[n]` Citations to typed sources.
4. **Gate before building**: measure reranker speed and recall on a small labelled question set in the Files comparison harness. If it's too slow, fall back to re-embedding Files with MiniLM. RRF across sources is ruled out (it degenerates to round-robin over disjoint lists).

### Citations

- **Cited Notes** get Strings, as today.
- **Cited File chunks and Papers** show as chips on the answer Note, e.g. `[2] lecture3.pdf p.4` or `[3] Vaswani 2017`. A chip opens the chunk preview, or the Paper in Research. No String, no proxy card.
- **Snapshot, not sync**: a chip keeps its quoted text and label from ask time. If the source is gone it shows "source removed" and opens nothing.
- **Pin to canvas**: an explicit action on a chip turns that File chunk or Paper into a real Note with a String (Papers reuse Send to board). It never happens automatically.

## Build slices

Each slice is demoable end to end, and each is tested with pytest in the existing `backend/tests` style, with Ollama faked. Slice issues are not created yet. Implementing Boards is a separate effort from this map.

| # | Slice | Depends on |
|---|---|---|
| 1 | Boards table, v13 migration into "General", `board_id` on notes and folders, Board-scoped Ask and suggestions | — |
| 2 | Header switcher, URL, create, rename, delete with typed confirmation | 1 |
| 3 | Domain description preamble on extraction and enrichment | 1 |
| 4 | Move Notes between Boards (String cutting, re-extraction, undo, toast) | 1, 3 |
| 5 | Files folders inside a Board (scoped Files tab and Files Ask, per-Board names) | 1, Files pipeline merged |
| 6 | Board sources: Add to Board, Send-to-board attach, Sources list with remove | 1 |
| 7 | Typed Citations and chips on answers, Pin to canvas | 1 |
| 8 | Phase 2 Board Ask: per-source candidates + cross-encoder rerank (after the measurement gate) | 5, 6, 7 |

## Out of scope

- Ask or search across Boards.
- An LLM-drafted domain description.
- Hints for misfiled notes.
- Archiving a Board, and exporting a single Board.
- Board-scoped Research Ask.
- A search-and-add Sources list inside the Board (v1 attaches from Research).
