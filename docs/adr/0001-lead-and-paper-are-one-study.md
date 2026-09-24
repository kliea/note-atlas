# Lead and Paper are one Study entity

In the Research Track, a Lead becomes a Paper when the user uploads its PDF. We store both as a single **Study** that changes state, rather than as separate `leads` and `papers` tables, so a Study keeps its identity and every cites edge (Parent, Sibling, Ancestor) across the upload with nothing to re-point. Deleting a Paper turns it back into a Lead, which is how its Lineage survives.

## Considered Options

- **Separate `leads` and `papers` tables** — rejected: every upload would have to migrate edges from the Lead to the new Paper, and a failure partway through would break the Lineage.
- **Paper as a board Note (`notes.kind = 'paper'`)** — rejected: notes carry board-only state (position, ink, the rephrase pipeline), and the Research Track is a separate workspace; every board query would have to filter Papers out.
