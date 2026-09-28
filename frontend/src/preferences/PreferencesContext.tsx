import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

import { api, type UserPreferences } from "../api/native";
import { applyAppearance, watchSystemMode } from "../theme/appearance";

// Several quick changes (e.g. dragging the crossfade slider) make one request.
const SAVE_DELAY_MS = 400;

interface PreferencesValue {
  /** null until loaded from the server. */
  preferences: UserPreferences | null;
  /**
   * Changes the preferences: `change` gets the latest ones (not those of the last
   * render, so quick successive changes all apply). Applies at once, saved shortly after.
   * Does nothing until the preferences are loaded.
   */
  update(change: (current: UserPreferences) => UserPreferences): void;
  /** The last save failed (shown on the Account page). */
  saveError: string | null;
}

const PreferencesContext = createContext<PreferencesValue | null>(null);

/** The signed-in user's preferences, stored on the server (they follow the user). */
export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<UserPreferences | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const current = useRef<UserPreferences | null>(null);
  const pending = useRef<{ timer: ReturnType<typeof setTimeout>; value: UserPreferences } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getPreferences()
      .then((loaded) => {
        if (cancelled) return;
        current.current = loaded;
        setPreferences(loaded);
      })
      .catch(() => {
        // Keep the theme remembered in this browser; retried at the next sign-in.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const flush = useCallback(() => {
    const save = pending.current;
    if (!save) return;
    clearTimeout(save.timer);
    pending.current = null;
    api
      .setPreferences(save.value)
      .then(() => setSaveError(null))
      .catch((e: unknown) => setSaveError(e instanceof Error ? e.message : String(e)));
  }, []);

  // Unsaved changes are sent when leaving (sign out, closing the tab).
  useEffect(() => {
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      flush();
    };
  }, [flush]);

  const update = useCallback(
    (change: (current: UserPreferences) => UserPreferences) => {
      if (!current.current) return;
      const next = change(current.current);
      if (next === current.current) return; // nothing changed: nothing to save
      current.current = next;
      setPreferences(next);
      if (pending.current) clearTimeout(pending.current.timer);
      pending.current = { value: next, timer: setTimeout(flush, SAVE_DELAY_MS) };
    },
    [flush],
  );

  // The theme follows the preferences, and the OS when the mode is "system".
  const theme = preferences?.theme;
  useEffect(() => {
    if (!theme) return;
    applyAppearance(theme);
    return theme.mode === "system" ? watchSystemMode(() => applyAppearance(theme)) : undefined;
  }, [theme]);

  return (
    <PreferencesContext.Provider value={{ preferences, update, saveError }}>{children}</PreferencesContext.Provider>
  );
}

export function usePreferences(): PreferencesValue {
  const value = useContext(PreferencesContext);
  if (!value) throw new Error("usePreferences must be used inside <PreferencesProvider>");
  return value;
}
