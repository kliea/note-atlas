// Where the board's view was last centred (board coordinates). The Research Track reads it
// so a Claim sent to the board lands where the user was last looking. Per-browser only;
// losing it just means the note takes the board's default spot.
const KEY = "atlas.board.centre";

export type BoardCentre = { x: number; y: number };

export function saveBoardCentre(centre: BoardCentre): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(centre));
  } catch {
    // storage unavailable: nothing to remember
  }
}

export function loadBoardCentre(): BoardCentre | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<BoardCentre>;
    return typeof value.x === "number" && typeof value.y === "number" ? { x: value.x, y: value.y } : null;
  } catch {
    return null;
  }
}
