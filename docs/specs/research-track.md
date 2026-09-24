# Research Track — implementation spec

A separate workspace in Note Atlas where the user uploads a **Paper**'s PDF, reads its **Extraction** (metadata, research question, method, key results, scope, **Claims**), and follows titled **Leads** — Parent, Sibling, and Ancestor studies — to find and upload next, growing the **Lineage**.

Vocabulary: [`CONTEXT.md`](../../CONTEXT.md). Key structural decision: [ADR 0001 — Lead and Paper are one Study](../adr/0001-lead-and-paper-are-one-study.md). Every decision below links the wayfinder ticket that holds its full reasoning; the map is [issue #2](https://github.com/kliea/note-atlas/issues/2).

## Principles

- **Local first.** PDFs, Extractions, and notes never leave the machine. Only titles/DOIs/OpenAlex ids go to the scholarly API, which is on by default for the Research Track and can be switched off. The board stays fully local.
- **Atlas never downloads papers.** It names Leads with DOI / arXiv / open-access links; the user uploads.
- **Claims are honest.** A paper's Limitation exists only if the paper says it, verified against its own words. The user's own Claims are marked as theirs.
- **User intent is sticky.** Edits, reader Claims, deletions, Parent marks, and dismissals survive every recompute and re-extraction.

## Components

| Component | Choice | Decision |
|---|---|---|
| PDF parsing | GROBID 0.9.1 CRF, Docker arm64 image, bound to `127.0.0.1:8070`, **started on demand** per upload batch and stopped ~2 min after the queue empties (~13 s cold start, ~3.7 GB peak). Always `consolidateHeader=0`, `consolidateCitations=0`, `includeRawCitations=1`. PyMuPDF text-only fallback. | [#3](https://github.com/kliea/note-atlas/issues/3), [#8](https://github.com/kliea/note-atlas/issues/8) |
| Scholarly API | OpenAlex primary (keyless $0.10/day, free key $1/day); Semantic Scholar optional with the user's own key; Crossref title→DOI fallback. Responses cached in SQLite by DOI/OpenAlex id. | [#4](https://github.com/kliea/note-atlas/issues/4), [#12](https://github.com/kliea/note-atlas/issues/12) |
| Local model | `qwen3:4b` (`think: false`, `temperature: 0`), explicit `num_ctx`, `truncate: false`, `shift: false`; one schema-constrained call over the body, chunk-then-merge above ~24K tokens. | [#5](https://github.com/kliea/note-atlas/issues/5) |
| Embeddings | Existing MiniLM + sqlite-vec (Sibling similarity, Claim matching, Research Track Ask). | [#9](https://github.com/kliea/note-atlas/issues/9), [#14](https://github.com/kliea/note-atlas/issues/14) |

## Data model (migration v6 in `notes.db`)

Decision: [#6](https://github.com/kliea/note-atlas/issues/6), extended by [#10](https://github.com/kliea/note-atlas/issues/10), [#11](https://github.com/kliea/note-atlas/issues/11), [#13](https://github.com/kliea/note-atlas/issues/13).

- **Study** — one entity, state `lead | paper`. Metadata (title, authors, year, venue, DOI, arXiv id, OpenAlex id, OA link). For Papers: PDF at `data/papers/<study-id>.pdf`, Extraction text fields (research question, method, key results, scope), extraction provenance (model, parser version, date). Deleting a Paper removes the file and reverts it to a Lead.
- **Claim** — one row per Contribution or Limitation: kind, text, author (`paper | reader`), verified quote, order, edited flag + original text, `stale` flag ("not in the latest extraction"), sent-to-board marker. Deleting a paper Claim leaves a **tombstone** (original text) instead of a hard delete.
- **Cites edge** — Paper → Study for every bibliography entry (a Reference): raw reference string, in-text mention count, citation-context sentences, **Parent score + reason**, user Parent mark (pinned/unpinned). API-found Siblings are stored as Leads with their own cites edge to the shared Parent.
- **Lead dismissal** — per (Paper, Study) "not relevant".
- **Job** — one row per Paper upload: current step, per-step status, error.
- **Setting** — scholarly API on/off (keys are **not** stored here).
- **Board note** — gains a nullable Study + Claim reference; new `source="paper"`.
- **Identity** — auto-merge on DOI / arXiv id / OpenAlex id; fuzzy title+year asks the user; merging re-points edges to the survivor.

## Pipeline (upload → Paper)

Decision: [#11](https://github.com/kliea/note-atlas/issues/11).

A persisted job queue drained by **one in-process worker, one Paper at a time**, resuming from the last completed step after restart. The frontend polls, like the board's `extract_status`.

1. **Store** the PDF, create the Study.
2. **Parse** with GROBID → the Paper appears in the Library.
3. **Resolve** metadata and References via OpenAlex (network) — **in parallel with** 4.
4. **Extract** (Extraction fields + Contributions), then the **Limitations pass**.
5. **Select Parents.**
6. **Find Siblings and Ancestors.**

Identity confirmation after step 3 never blocks the job. Batches queue FIFO ("waiting (Nth in line)"). Failures retry from the failed step. Board polish jobs get the model first; the Paper job yields between model steps.

## Extraction rules

Decision: [#8](https://github.com/kliea/note-atlas/issues/8).

- Research question (one sentence), method, key results (keep the paper's numbers), scope — free text.
- **Contributions** — what the authors claim is new about their own work. Findings are not Contributions; the prompt forbids restating key results.
- **Paper Limitations** — kept only if the quote **fuzzy-matches the full text** and a **second model check confirms the quote states a limitation**; otherwise dropped.
- One Claim per distinct point; drop umbrella items.
- Year / DOI come from OpenAlex, not the GROBID header.

## Leads

Decision: [#9](https://github.com/kliea/note-atlas/issues/9).

- **Parents** — heuristic shortlist (~15: mentions weighted by section, plus S2 `isInfluential`/`intents` when keyed) → local model picks with score + one-line reason. Fallback when citations aren't linked: model reads the reference list against the Method section. Show top 5 above a threshold; "show more" by score.
- **Siblings** — OpenAlex works citing any Parent. Rank: in Library first → number of shared Parents → MiniLM abstract similarity → recency. Exclude this Paper's own References. Cap 5 + show more.
- **Ancestors** — References of Parents, ranked by how many of this Paper's Parents cite them, tie-break `fwci`. 2 hops × ≤3 + show more. Replaced by real Parents once a Parent is uploaded.
- **Recompute** on Paper upload, on Lead upload (every Paper that listed it), and on manual "refresh leads". No schedule.
- **API off / budget exhausted** — Parents still work (no links); Siblings only from the Library; Ancestors only via uploaded Parents; one explanatory line. A 429 pauses network steps and auto-resumes at reset ([#12](https://github.com/kliea/note-atlas/issues/12)).

## UI

Decision: [#7](https://github.com/kliea/note-atlas/issues/7); prototype on branch `prototype/research-track-ui`.

- `Board | Research` toggle in the top bar.
- **Library table** (search; Papers / Leads / All; `+ Upload PDF`) with a **reader pane**: metadata + links, Extraction fields, Claim cards (yours / edited / stale badges; quote; edit; → send to board; + add your Limitation), per-section progress states.
- **Lineage tab** → column graph: Ancestors → Parents → Paper → Siblings; Leads dashed; edge weight by mentions; click selects, double-click re-centres.
- **Upload dialog** as prototyped: drop → "Is this the Lead you already have?" → progress list; closable.
- **Status pill** in the header: `OpenAlex · on · $0.07 left today` (`+ S2`); click toggles the API.

## Send to board

Decision: [#13](https://github.com/kliea/note-atlas/issues/13).

Note = Claim text (title) + quote + attribution line; `source="paper"` skips rephrase but keeps topics/embedding; first Claim from a Paper lands at the last board viewport centre, later ones group beside it; Paper chip ↔ "on board ↗" badge; snapshot with no sync either way.

## Ask

Decision: [#14](https://github.com/kliea/note-atlas/issues/14).

Over Extraction fields and Claims only (no full text, no Leads); scope = selected Library rows or the whole Library; answer in the reader pane with citations to the exact Claim/field; declines rather than invents; can be sent to the board as `source="ask"`; no crossover with board Ask.

## Re-extraction

Decision: [#10](https://github.com/kliea/note-atlas/issues/10).

User-triggered only. Untouched paper Claims are replaced; edited and sent Claims carry over by MiniLM match on original text, else flagged stale; reader Claims untouched; tombstones suppress rejected Claims; no history, provenance only.

## Configuration

`.env` gains `OPENALEX_API_KEY`, `S2_API_KEY`, `CROSSREF_MAILTO` (all optional); document in `.env.example`. Update the stale `OLLAMA_MODEL` default to `qwen3:4b`.

## Build slices

Each slice is demoable end to end. Acceptance for every slice: pytest with GROBID / Ollama / OpenAlex faked (existing `backend/tests` style) **and** a manual demo on the three papers from [#8](https://github.com/kliea/note-atlas/issues/8) (plus one later-uploaded Lead for the Lead → Paper path).

| # | Slice | Depends on |
|---|---|---|
| 1 | [Upload → Paper in the Library](https://github.com/kliea/note-atlas/issues/16) | — |
| 2 | [Extraction and Claims in the reader](https://github.com/kliea/note-atlas/issues/17) | 1 |
| 3 | [OpenAlex resolution and identity](https://github.com/kliea/note-atlas/issues/18) | 2 |
| 4 | [Parent Papers](https://github.com/kliea/note-atlas/issues/19) | 3 |
| 5 | [Siblings, Ancestors, and the Lineage graph](https://github.com/kliea/note-atlas/issues/20) | 4 |
| 6 | [Send to board](https://github.com/kliea/note-atlas/issues/21) | 2 |
| 7 | [Research Track Ask](https://github.com/kliea/note-atlas/issues/22) | 2 |
| 8 | [Re-extraction](https://github.com/kliea/note-atlas/issues/23) | 2, 6 |

Each slice has its own issue with demo and acceptance checks.

## Out of scope

- Atlas fetching or downloading PDFs on its own.
- Unbounded ancestry crawling or whole-field literature discovery.
- Ask over full paper text or Leads' abstracts.
- A settings UI for keys (v1 uses `.env`).
- Extraction history beyond provenance.
