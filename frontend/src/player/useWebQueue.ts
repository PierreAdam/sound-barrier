import { useEffect, useRef, useSyncExternalStore } from "react";

import { ApiError, api, type SavedQueue } from "../api/native";
import { useSession } from "../auth/AuthContext";
import type { PlayerEngine, PlayerSnapshot, QueueState } from "./engine";
import { songToTrack } from "./tracks";
import { setWebPlayerId, useWebPlayerId } from "./webPlayer";

// A burst of changes (several songs removed...) makes one save.
const SAVE_DELAY_MS = 1000;
// While playing, the position is saved this often (and on pause, track change, leaving).
const POSITION_EVERY_MS = 20_000;
// keepalive requests (sent while the page closes) are limited to 64 KB by browsers.
const KEEPALIVE_MAX_SONGS = 1200;

const EMPTY: SavedQueue = { revision: 0, songs: [], originalOrder: null, currentIndex: -1, positionMs: 0, updatedAt: null };

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
 *
 * It is the queue of the player this browser is assigned to (webPlayer.ts): the Shared
 * one, or one the user created. Switching saves this queue to the player it belongs to,
 * pauses, and brings the other player's. A player deleted meanwhile (the server no longer
 * knows it): back to Shared.
 */
export function useWebQueue(engine: PlayerEngine): void {
  const { username } = useSession().user;
  const playerId = useWebPlayerId(username);
  const state = useSyncExternalStore(engine.subscribe, engine.getSnapshot);
  const sync = useRef({
    ready: false, // the saved queue was loaded (or could not be): saving is allowed
    loaded: false, // the first queue was loaded: the next ones replace this one (a switch)
    playerId, // whose queue the engine has
    lost: false, // that player no longer exists: nothing to save to it
    revision: 0, // of the server queue this browser has, or last saved
    signature: "", // of the queue last saved or restored
    timer: null as ReturnType<typeof setTimeout> | null,
  });

  // The server does not know the player (deleted): this browser goes back to Shared.
  const lostRef = useRef((error: unknown, id: string | null): boolean => {
    if (!(error instanceof ApiError && error.status === 404 && id)) return false;
    if (sync.current.playerId === id) sync.current.lost = true;
    setWebPlayerId(username, null);
    return true;
  });

  // Saves the engine's queue now (to the player it belongs to).
  const saveRef = useRef((keepalive = false) => {
    const current = sync.current;
    if (!current.ready || current.lost) return;
    if (current.timer) clearTimeout(current.timer);
    current.timer = null;
    current.signature = signatureOf(engine.getSnapshot());
    const queue = engine.exportQueue();
    const id = current.playerId;
    api
      .saveQueue(
        id,
        {
          songIds: queue.tracks.map((track) => track.id),
          originalOrder: queue.originalOrder,
          currentIndex: queue.index,
          positionMs: Math.round(queue.position * 1000),
        },
        keepalive && queue.tracks.length <= KEEPALIVE_MAX_SONGS,
      )
      .then(({ revision }) => {
        if (current.playerId === id) current.revision = Math.max(current.revision, revision);
      })
      .catch((error: unknown) => {
        // Offline: saved again at the next change or position tick.
        lostRef.current(error, id);
      });
  });

  const restore = (saved: SavedQueue) => {
    const current = sync.current;
    current.revision = saved.revision;
    engine.restoreQueue(toState(saved));
    current.signature = signatureOf(engine.getSnapshot());
  };

  // Opening the web UI: bring back the saved queue (unless something was queued first).
  // Switching player: this queue is saved to its player, then the other one replaces it.
  useEffect(() => {
    let cancelled = false;
    const current = sync.current;
    const switching = current.loaded && current.playerId !== playerId;
    if (switching) {
      // Like leaving the page: only what this browser has not saved yet (a change, the
      // position while playing). Otherwise the player may have a newer queue, from
      // another device.
      if (current.timer || engine.getSnapshot().playing) saveRef.current();
      engine.pause();
    }
    current.ready = false;
    current.lost = false;
    current.playerId = playerId;
    current.revision = 0;
    // An empty player is not a change to save: only what gets queued from now on is.
    current.signature = signatureOf(engine.getSnapshot());
    api
      .getQueue(playerId)
      .then((saved) => {
        if (cancelled) return;
        current.revision = saved.revision;
        if (switching || (saved.songs.length && engine.getSnapshot().queue.length === 0)) restore(saved);
      })
      .catch((error: unknown) => {
        if (cancelled || lostRef.current(error, playerId)) return; // Shared is loaded instead
        // Offline: rather an empty queue than the other player's (saved over this one's).
        if (switching) restore(EMPTY);
      })
      .finally(() => {
        if (cancelled || current.lost) return;
        current.loaded = true;
        current.ready = true;
        // Queued while loading: that queue wins, save it.
        if (signatureOf(engine.getSnapshot()) !== current.signature) saveRef.current();
      });
    return () => {
      cancelled = true;
    };
  }, [engine, playerId]);

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
      const id = current.playerId;
      api
        .getQueueRevision(id)
        .then(async ({ revision }) => {
          if (revision <= current.revision) return;
          const saved = await api.getQueue(id);
          if (!engine.getSnapshot().playing && !current.timer && current.playerId === id) restore(saved);
        })
        .catch((error: unknown) => lostRef.current(error, id));
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [engine]);
}
