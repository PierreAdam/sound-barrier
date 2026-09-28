// Theme selection: applies the user's appearance preferences to the page.
// The palettes themselves are in theme.less (data-theme / data-accent on <html>).

export type ThemeMode = "dark" | "light" | "system";

export interface Appearance {
  mode: ThemeMode;
  accent: string;
}

/** Accent palettes defined in theme.less (`.accent-palette(...)`), in display order. */
export const ACCENTS = [
  { id: "teal", label: "Teal" },
  { id: "blue", label: "Blue" },
  { id: "violet", label: "Violet" },
  { id: "pink", label: "Pink" },
  { id: "orange", label: "Orange" },
  { id: "green", label: "Green" },
] as const;

export const DEFAULT_APPEARANCE: Appearance = { mode: "dark", accent: "teal" };

// Also read by the inline script of index.html, before the page is drawn (no flash of
// the wrong theme): keep the key and the format in sync with it.
const STORAGE_KEY = "sound-barrier.appearance";
const SYSTEM_LIGHT = "(prefers-color-scheme: light)";

export function resolveMode(mode: ThemeMode): "dark" | "light" {
  if (mode !== "system") return mode;
  return typeof matchMedia === "function" && matchMedia(SYSTEM_LIGHT).matches ? "light" : "dark";
}

function knownAccent(accent: string): string {
  return ACCENTS.some((a) => a.id === accent) ? accent : DEFAULT_APPEARANCE.accent;
}

/** Applies `appearance` to the page and remembers it for the next visit. */
export function applyAppearance(appearance: Appearance): void {
  const root = document.documentElement;
  root.dataset.theme = resolveMode(appearance.mode);
  root.dataset.accent = knownAccent(appearance.accent);
  // Browser UI color (mobile address bar...): the page background.
  const background = getComputedStyle(root).getPropertyValue("--color-bg").trim();
  if (background) document.querySelector('meta[name="theme-color"]')?.setAttribute("content", background);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(appearance));
  } catch {
    // storage unavailable: the theme is still applied for this visit
  }
}

/** Calls `onChange` when the OS switches between light and dark. */
export function watchSystemMode(onChange: () => void): () => void {
  if (typeof matchMedia !== "function") return () => undefined;
  const query = matchMedia(SYSTEM_LIGHT);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
