import type { AppView } from "./components/ViewNav";

export const BOARD_HASH = "#/board";

export function viewFromHash(hash: string): AppView | null {
  const path = hash.replace(/^#/, "").replace(/^\//, "").toLowerCase();
  if (path === "board") {
    return "board";
  }
  return null;
}

export function hashFromView(view: AppView): string {
  return view === "board" ? BOARD_HASH : "";
}

export function syncHash(view: AppView): void {
  const wanted = hashFromView(view);
  const current = window.location.hash;
  if (wanted === BOARD_HASH) {
    if (viewFromHash(current) !== "board") {
      window.location.hash = BOARD_HASH;
    }
    return;
  }
  if (viewFromHash(current) === "board") {
    const url = `${window.location.pathname}${window.location.search}`;
    window.history.replaceState(null, "", url);
  }
}
