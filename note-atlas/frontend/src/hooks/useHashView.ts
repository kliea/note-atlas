import { useCallback, useEffect, useState } from "react";
import type { AppView } from "../components/ViewNav";
import { syncHash, viewFromHash } from "../hashView";

const DEFAULT_VIEW: AppView = "capture";

export function useHashView(): [AppView, (next: AppView) => void] {
  const [view, setView] = useState<AppView>(
    () => viewFromHash(window.location.hash) ?? DEFAULT_VIEW,
  );

  const onChange = useCallback((next: AppView) => {
    setView(next);
    syncHash(next);
  }, []);

  useEffect(() => {
    function onHashChange(): void {
      const fromHash = viewFromHash(window.location.hash);
      if (fromHash !== null) {
        setView(fromHash);
        return;
      }
      setView((current) => (current === "board" ? DEFAULT_VIEW : current));
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return [view, onChange];
}
