import { useEffect, useRef, useSyncExternalStore } from "react";

import { api, type SavedQueue } from "../api/native";
import type { PlayerEngine, PlayerSnapshot, QueueState } from "./engine";
import { songToTrack } from "./tracks";

// A burst of changes (several songs removed...) makes one save.
const SAVE_DELAY_MS = 1000;
// While playing, the position is saved this often (and on pause, track change, leaving).
const POSITION_EVERY_MS = 20_000;
// keepalive requests (sent while the page closes) are limited to 64 KB by browsers.
const KEEPALIVE_MAX_SONGS = 1200;

/** What makes the queue different, the position aside. */
function signatureOf(state: PlayerSnapshot): string {
  return `${state.shuffle ? "s" : "o"}|${state.index}|${state.keys.join(",")}`;
}

function toState(saved: SavedQueue): QueueState {
  return {
    tracks: saved.songs.map(songToTrack),
    originalOrder: saved.originalOrder,
    index: saved.currentIndex,
    position: saved.positionMs / 1000,
  };
}

/**
 * The web queue follows the user from one browser to another (like the original
 * Subsonic web player): restored when the web UI opens, saved when it changes and while
 * playing. When the tab becomes visible again and is not playing, a queue changed on
 * another computer meanwhile replaces this one. Subsonic apps keep their own queue.
 */
export function useWebQueue(engine: PlayerEngine): void {
  const state = useSyncExternalStore(engine.subscribe, engine.getSnapshot);
  const sync = useRef({
    ready: false, // the saved queue was loaded (or could not be): saving is allowed
    revision: 0, // of the server queue this browser has, or last saved
    signature: "", // of the queue last saved or restored
    timer: null as ReturnType<typeof setTimeout> | null,
  });

  // Saves the engine's queue now.
  const saveRef = useRef((keepalive = false) => {
    const current = sync.current;
    if (!current.ready) return;
    if (current.timer) clearTimeout(current.timer);
    current.timer = null;
    current.signature = signatureOf(engine.getSnapshot());
    const queue = engine.exportQueue();
    api
      .saveQueue(
        {
          songIds: queue.tracks.map((track) => track.id),
          originalOrder: queue.originalOrder,
          currentIndex: queue.index,
          positionMs: Math.round(queue.position * 1000),
        },
        keepalive && queue.tracks.length <= KEEPALIVE_MAX_SONGS,
      )
      .then(({ revision }) => {
        current.revision = Math.max(current.revision, revision);
      })
      .catch(() => {
        // Offline: saved again at the next change or position tick.
      });
  });

  const restore = (saved: SavedQueue) => {
    const current = sync.current;
    current.revision = saved.revision;
    engine.restoreQueue(toState(saved));
    current.signature = signatureOf(engine.getSnapshot());
  };

  // Opening the web UI: bring back the saved queue (unless something was queued first).
  useEffect(() => {
    let cancelled = false;
    const current = sync.current;
    // An empty player is not a change to save: only what gets queued from now on is.
    current.signature = signatureOf(engine.getSnapshot());
    api
      .getQueue()
      .then((saved) => {
        if (cancelled) return;
        current.revision = saved.revision;
        if (saved.songs.length && engine.getSnapshot().queue.length === 0) restore(saved);
      })
      .catch(() => undefined)
      .finally(() => {
        if (cancelled) return;
        current.ready = true;
        // Queued while loading: that queue wins, save it.
        if (signatureOf(engine.getSnapshot()) !== current.signature) saveRef.current();
      });
    return () => {
      cancelled = true;
    };
  }, [engine]);

  // Queue changes (and track changes): saved shortly after.
  useEffect(() => {
    const current = sync.current;
    if (!current.ready || signatureOf(state) === current.signature || current.timer) return;
    current.timer = setTimeout(() => saveRef.current(), SAVE_DELAY_MS);
  }, [state]);

  // The position: regularly while playing, and when pausing.
  const playing = state.playing;
  const wasPlaying = useRef(false);
  useEffect(() => {
    if (wasPlaying.current && !playing) saveRef.current();
    wasPlaying.current = playing;
    if (!playing) return;
    const timer = setInterval(() => saveRef.current(), POSITION_EVERY_MS);
    return () => clearInterval(timer);
  }, [playing]);

  // Leaving the page (closing the tab, reloading, signing out): only a tab with a change
  // not saved yet, or playing (its position moved), saves. A tab left open with an old
  // queue must not overwrite the one saved since by another computer.
  useEffect(() => {
    const onHide = () => {
      if (sync.current.timer || engine.getSnapshot().playing) saveRef.current(true);
    };
    window.addEventListener("pagehide", onHide);
    return () => {
      window.removeEventListener("pagehide", onHide);
      onHide();
    };
  }, [engine]);

  // Back on this tab: take the queue another computer saved meanwhile, unless playing
  // here (then this one wins at its next save) or a change of ours is waiting.
  useEffect(() => {
    const onVisible = () => {
      const current = sync.current;
      if (document.visibilityState !== "visible" || !current.ready || current.timer) return;
      if (engine.getSnapshot().playing) return;
      api
        .getQueueRevision()
        .then(async ({ revision }) => {
          if (revision <= current.revision) return;
          const saved = await api.getQueue();
          if (!engine.getSnapshot().playing && !current.timer) restore(saved);
        })
        .catch(() => undefined);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [engine]);
}
