// A new cover under the same coverArt id (an admin chose another album cover): browsers
// reuse an image already shown on the page for an identical URL without asking the server
// again, so the old one would stay until a reload. A changed cover gets a version, added to
// its URLs ("rev"), and every <CoverArt> of it loads the new one at once.

import { useSyncExternalStore } from "react";

const versions = new Map<string, number>();
const listeners = new Set<() => void>();

/** The covers with these ids changed (e.g. the album's old and new coverArt). */
export function bumpCovers(...ids: (string | null | undefined)[]): void {
  const stamp = Date.now();
  for (const id of ids) if (id) versions.set(id, stamp);
  listeners.forEach((listener) => listener());
}

/** Extra URL parameters for a cover: its version, once changed ({} otherwise). */
export function coverVersion(id: string | undefined): { rev?: number } {
  const version = id ? versions.get(id) : undefined;
  return version ? { rev: version } : {};
}

export function useCoverVersion(id: string | undefined): number | undefined {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => (id ? versions.get(id) : undefined),
  );
}
