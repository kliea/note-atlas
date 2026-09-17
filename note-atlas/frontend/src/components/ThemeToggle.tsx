import type { ThemePref } from "../hooks/useTheme";

type ThemeToggleProps = {
  pref: ThemePref;
  onCycle: () => void;
};

function label(pref: ThemePref): string {
  if (pref === "system") {
    return "Theme: system";
  }
  if (pref === "light") {
    return "Theme: light";
  }
  return "Theme: dark";
}

export function ThemeToggle({ pref, onCycle }: ThemeToggleProps) {
  return (
    <button type="button" className="nav-btn theme-toggle" onClick={onCycle} aria-label={label(pref)}>
      {label(pref)}
    </button>
  );
}
