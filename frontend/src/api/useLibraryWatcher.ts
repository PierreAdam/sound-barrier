import { useEffect } from "react";

import { api } from "./native";
import { invalidateSubsonicCache } from "./useSubsonic";

const POLL_MS = 10_000;

/**
 * Compares the server's library revision with the last one seen and calls `onChange`
 * when it moved. The first check only sets the reference, even in a hidden tab: a change
 * made while the tab is hidden must still be noticed once it is visible again. Later
 * checks are skipped while hidden.
 */
export function createRevisionCheck(
  fetchRevision: () => Promise<number>,
  onChange: () => void,
  isVisible: () => boolean,
): () => Promise<void> {
  let known: number | null = null;
  return async () => {
    if (known !== null && !isVisible()) return;
    try {
      const revision = await fetchRevision();
      if (known !== null && revision !== known) onChange();
      known = revision;
    } catch {
      // Offline or signed out: try again at the next tick.
    }
  };
}

/**
 * Reloads the cached library lists (side menu, artist and album pages...) when the
 * library changed on the server: an import or a deletion (from any page or any admin),
 * a scheduled scan... Polls a small revision number while the tab is visible.
 */
export function useLibraryWatcher(): void {
  useEffect(() => {
    let active = true;
    const check = createRevisionCheck(
      async () => (await api.getLibraryRevision()).revision,
      () => {
        if (active) invalidateSubsonicCache();
      },
      () => document.visibilityState === "visible",
    );
    void check();
    const timer = setInterval(() => void check(), POLL_MS);
    // Back on the tab: check at once rather than at the next tick.
    const onVisible = () => void check();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      active = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);
}
