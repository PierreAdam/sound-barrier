import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { useSession } from "../auth/AuthContext";
import type { Params, SubsonicClient } from "./subsonic";
import type { SubsonicMethod, SubsonicResponse } from "./types";

// Short-lived shared cache: several components showing the same data (e.g. the artist
// list in the side panel and on Browse) make one request.
const CACHE_TTL_MS = 5 * 60 * 1000;
const cache = new Map<string, { time: number; promise: Promise<unknown> }>();
let cacheVersion = 0;
const cacheListeners = new Set<() => void>();

/** Drops cached responses (e.g. after a library scan); mounted views reload. */
export function invalidateSubsonicCache(): void {
  cache.clear();
  cacheVersion += 1;
  cacheListeners.forEach((listener) => listener());
}

function subscribeCache(listener: () => void): () => void {
  cacheListeners.add(listener);
  return () => cacheListeners.delete(listener);
}

function cachedCall<M extends SubsonicMethod>(
  client: SubsonicClient,
  method: M,
  params: Params,
  fresh: boolean,
): Promise<SubsonicResponse<M>> {
  const key = `${client.username}|${method}|${JSON.stringify(params)}`;
  const hit = cache.get(key);
  if (!fresh && hit && Date.now() - hit.time < CACHE_TTL_MS) {
    return hit.promise as Promise<SubsonicResponse<M>>;
  }
  const promise = client.call(method, params);
  cache.set(key, { time: Date.now(), promise });
  promise.catch(() => cache.delete(key)); // never cache failures
  return promise;
}

interface Result<M extends SubsonicMethod> {
  data: SubsonicResponse<M> | null;
  error: Error | null;
  loading: boolean;
  reload(): void;
}

/** Calls a Subsonic method when the component mounts (and when `params` change). */
export function useSubsonic<M extends SubsonicMethod>(method: M, params: Params = {}): Result<M> {
  const { client } = useSession();
  const [data, setData] = useState<SubsonicResponse<M> | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [forced, setForced] = useState(0);
  const version = useSyncExternalStore(subscribeCache, () => cacheVersion);
  const paramsKey = JSON.stringify(params);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    cachedCall(client, method, JSON.parse(paramsKey) as Params, forced > 0)
      .then((response) => {
        if (cancelled) return;
        setData(response);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e : new Error(String(e)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, method, paramsKey, forced, version]);

  const reload = useCallback(() => setForced((n) => n + 1), []);
  return { data, error, loading, reload };
}
