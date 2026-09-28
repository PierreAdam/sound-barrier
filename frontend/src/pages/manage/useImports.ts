import { useCallback, useEffect, useRef, useState } from "react";

import { api, type ImportJob, type ImportTask } from "../../api/native";
import { invalidateSubsonicCache } from "../../api/useSubsonic";

const POLL_ACTIVE_MS = 1500;
const POLL_IDLE_MS = 10000;
const ACTIVE: ImportTask["status"][] = ["queued", "analyzing", "converting", "applying"];

export interface Imports {
  jobs: ImportJob[];
  /** Albums waiting for a decision (and failed ones, to retry). */
  review: ImportTask[];
  error: string | null;
  refresh(): Promise<void>;
}

/** Recent import jobs, refreshed often while something is being imported. */
export function useImports(): Imports {
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const importedCount = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.listImports();
      setJobs(next);
      setError(null);
      // New albums in the library: reload artists / albums everywhere.
      const imported = next.flatMap((j) => j.tasks).filter((t) => t.status === "imported").length;
      if (importedCount.current !== null && imported > importedCount.current) invalidateSubsonicCache();
      importedCount.current = imported;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const active = jobs.some(
    (job) => job.status === "queued" || job.status === "running" || job.tasks.some((t) => ACTIVE.includes(t.status)),
  );

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), active ? POLL_ACTIVE_MS : POLL_IDLE_MS);
    return () => clearInterval(timer);
  }, [refresh, active]);

  const review = jobs
    .flatMap((job) => job.tasks)
    .filter((task) => task.status === "pending" || task.status === "failed")
    .sort((a, b) => a.id - b.id);

  return { jobs, review, error, refresh };
}
