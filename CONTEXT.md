# Note Atlas

A local-first spatial notebook: thoughts are captured as notes on a board, polished by a local LLM, and joined by strings.

## Language

**Board**:
The spatial canvas where everyday notes live and are linked.

**Note**:
A single card on the board; its first line is its title.

**String**:
A link between two notes, either drawn by the user or accepted from a suggestion.

**Research Track**:
A separate workspace, apart from the board, dedicated to reading and relating academic papers.
_Avoid_: research mode, research board, `research/` (that folder is the SCA experiment, unrelated)

**Study**:
Any academic work the Research Track knows about; it is either a Lead or a Paper.
_Avoid_: work, publication, document, article, source

**Paper**:
A Study whose PDF the user has uploaded, and which therefore has an Extraction.
_Avoid_: document, article, source

### Research Track

**Extraction**:
The structured reading of one Paper: its metadata, research question, contributions, method, key results, limitations, scope, and references.
_Avoid_: summary, key info

**Claim**:
A single Contribution or Limitation, individually editable and sendable to the board.

**Contribution**:
A single claim of novelty a Paper makes about its own work — a new dataset, method, analysis, or synthesis. A finding is not a Contribution; findings belong to the Paper's key results.

**Limitation**:
A single weakness or boundary a Paper explicitly admits (backed by its own words), or that a reader attributes to it.

**Scope**:
The conditions under which a Paper's results are claimed to hold (domain, data, setting).

**Reference**:
A Paper's citing of another Study, as listed in its bibliography; every Reference points at a Study, usually a Lead.
_Avoid_: citation (reserve for the act of citing)

**Parent Paper**:
A Reference that a Paper substantially builds on, as opposed to merely mentions; one hop up its lineage.
_Avoid_: mother source, major source

**Ancestor**:
A Parent Paper of a Parent Paper, and so on up the Lineage.

**Sibling**:
A study that shares a Parent Paper with a given Paper.

**Lead**:
A Study without an uploaded PDF, known only from a reference entry or API metadata; Atlas surfaces Leads as Parents, Siblings, or Ancestors worth reading. Uploading its PDF turns the same Study into a Paper.
_Avoid_: stub, placeholder, suggestion

**Lineage**:
The graph of Papers and Leads connected by parent relationships.

**Library**:
The Research Track's browsable collection of Papers.
