# A Note belongs to exactly one Board, and retrieval is scoped by pre-filter

Atlas grows from one canvas to many **Boards**, each holding one domain of knowledge. A Board owns its Notes and Files folders outright: a Note belongs to exactly one Board, Strings never cross Boards, and a Files folder belongs to exactly one Board. Studies are the exception. The Library stays global and a Board only *references* Studies, because a Paper often matters to more than one domain and uploading it once per Board would duplicate its Extraction and Lineage. Ask and suggestions stay inside one Board: sqlite-vec's `rowid IN (…the Board's chunks…)` pre-filter is exact (it is applied before top-k), and it keeps the Board id on `notes` alone, so moving a Note never touches the vector table.

## Considered Options

- **Notes shared across Boards (tags or many-to-many)** — rejected: every Ask, suggestion and String would have to decide which Board's context applies, and the domain description could no longer steer a Note's polish unambiguously.
- **A `board_id` metadata column on `chunk_vec`** — rejected for now: equally exact and about 1 ms at 3k notes, but it copies the Board id into the vector table, where it has to be rewritten whenever a Note moves. Revisit only if pre-filter timing becomes a problem (research: issue #26).
- **sqlite-vec partition key or one vector table per Board** — rejected: a partition key can't be updated, and each Board costs about 1.5 MB of chunk storage at minimum.
- **Each Board with its own Library** — rejected: the same Paper would be uploaded, extracted and resolved once per Board.

## Consequences

- Migration puts every existing Note and Files folder into one ordinary Board. You can rename or delete it like any other Board, except that the last Board can never be deleted.
- Deleting a Board deletes its Notes and Files folders after a confirmation that names the counts. Its referenced Studies are untouched.
- Moving Notes to another Board keeps Strings among the moved Notes and cuts Strings to Notes left behind (undoable).
- A Board references Studies, not just Papers: a referenced Lead starts feeding Ask once its PDF is uploaded. Sending a Claim to a Board adds its Paper to that Board's references.
- Files folder names are unique within a Board, not globally.
