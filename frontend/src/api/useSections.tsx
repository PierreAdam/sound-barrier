import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";

import { api, type SpokenKind } from "./native";

type Sections = Record<SpokenKind, boolean>;

interface SectionsValue {
  /** Podcasts / Audiobooks: on (by an admin) and with a folder. */
  sections: Sections;
  /** After an admin changed them (Settings). */
  refresh(): void;
}

const NONE: Sections = { podcasts: false, audiobooks: false };
const SectionsContext = createContext<SectionsValue>({ sections: NONE, refresh: () => undefined });

export function SectionsProvider({ children }: { children: ReactNode }) {
  const [sections, setSections] = useState<Sections>(NONE);
  const refresh = useCallback(() => {
    api
      .getSections()
      .then(setSections)
      .catch(() => setSections(NONE));
  }, []);
  useEffect(refresh, [refresh]);
  return <SectionsContext.Provider value={{ sections, refresh }}>{children}</SectionsContext.Provider>;
}

export function useSections(): SectionsValue {
  return useContext(SectionsContext);
}
