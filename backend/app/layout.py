"""Board layout for note positions. Origin is offset so nothing sits at (0, 0)."""

from __future__ import annotations

# Matches a comfortable note-card footprint on the NUI board.
ORIGIN_X = 240.0
ORIGIN_Y = 180.0
COL_WIDTH = 320.0
ROW_HEIGHT = 240.0
COLS = 4


def grid_position(index: int) -> tuple[float, float]:
    """Return (x, y) for the index-th note in a left-to-right, top-to-bottom grid."""
    if index < 0:
        raise ValueError("layout index must be >= 0")
    col = index % COLS
    row = index // COLS
    return (ORIGIN_X + col * COL_WIDTH, ORIGIN_Y + row * ROW_HEIGHT)
