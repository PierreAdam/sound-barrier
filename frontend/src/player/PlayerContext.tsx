import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { api, type CheckedBookmark, type SyncedBookmark } from "../api/native";
import { coverVersion } from "../api/coverVersions";
import type { SubsonicClient } from "../api/subsonic";
import { useSession } from "../auth/AuthContext";
import { usePreferences } from "../preferences/PreferencesContext";
import { SCREEN_TARGET, screenLink } from "../cast/tv/screenLink";
import { remoteLink } from "../remote/link";
import { type PlayerMode, playHere, usePlayerMode } from "../remote/mode";
import { deviceName } from "../remote/protocol";
import { RemoteController } from "../remote/RemoteController";
import { resumeAudio, suspendAudio } from "./audioGraph";
import { traceAudio } from "./audioTrace";
import { bookOf, CHECK_EVERY_MS, moveFor } from "./bookmarkSync";
import { createBookmarkKeeper, RESUME_FROM_S, FINISHED_S, STARTED_S } from "./bookmarks";
import type { PlayerController } from "./controller";
import { PlayerEngine, type PlayerSnapshot, type QueueState, type Track } from "./engine";
import { createScrobbler } from "./scrobble";
import { SEEK_STEP_S, shortcutFor } from "./shortcuts";
import { useWebQueue } from "./useWebQueue";

import { songToTrack } from "./tracks";

export type { Track } from "./engine";
export { songToTrack } from "./tracks";

interface PlayerValue {
  /** This tab's own player: plays here (paused while in remote mode). */
  local: PlayerEngine;
  /** What the UI drives: the local player, or the remote one (remote mode). */
  active: PlayerController;
  mode: PlayerMode;
}

/** Remote mode: the player the UI drives (another tab, or a server player). */
export type RemotePlayer = Extract<PlayerMode, { kind: "remote" }>;

const PlayerContext = createContext<PlayerValue | null>(null);

/**
 * Shown by the player bar: "Resumed at 12:34" after an audiobook / podcast resumed, or,
 * `from` another device, where the player moved (useBookmarks).
 */
export interface ResumeNotice {
  trackId: string;
  seconds: number;
  from?: {
    source: string | null; // e.g. "Chrome on Android"
    changedAt: string;
    tookOver: boolean; // it was playing here, and is now playing there: paused here
  };
}

interface ResumeValue {
  notice: ResumeNotice | null;
  startOver(): void;
  undo(): void;
  dismiss(): void;
}

const ResumeContext = createContext<ResumeValue>({
  notice: null,
  startOver: () => undefined,
  undo: () => undefined,
  dismiss: () => undefined,
});

export function useResumeNotice(): ResumeValue {
  return useContext(ResumeContext);
}

function safeLocalStorage(): Storage | null {
  try {
    return localStorage;
  } catch {
    return null;
  }
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  const { client } = useSession();
  // The client changes when the password (hence the token) changes: read it through a
  // ref so the engine, and the queue, survive it.
  const clientRef = useRef(client);
  clientRef.current = client;
  const engine = useMemo(
    () =>
      new PlayerEngine({
        streamUrl: (id) => clientRef.current.url("stream", { id }),
        storage: safeLocalStorage(),
        trace: traceAudio,
      }),
    [],
  );
  useEffect(() => {
    engine.attach(); // again after StrictMode's unmount (development)
    return () => engine.destroy();
  }, [engine]);
  const mode = usePlayerMode();
  const remote = useRemoteMode(engine, mode);
  const active: PlayerController = mode.kind === "remote" ? remote : engine;
  // What is tied to this tab's own playback stays with the local player.
  useMediaSession(engine, client);
  useSyncedPlayerPreferences(engine);
  useWebQueue(engine);
  useScrobbling(engine, client);
  useAudioResume(engine);
  const resume = useBookmarks(engine);
  // The keyboard drives what the player bar shows.
  useShortcuts(active);
  const value = useMemo(() => ({ local: engine, active, mode }), [engine, active, mode]);
  return (
    <PlayerContext.Provider value={value}>
      <ResumeContext.Provider value={resume}>{children}</ResumeContext.Provider>
    </PlayerContext.Provider>
  );
}

function usePlayerValue(): PlayerValue {
  const value = useContext(PlayerContext);
  if (!value) throw new Error("The player hooks must be used inside <PlayerProvider>");
  return value;
}

/**
 * Player state (re-renders on change) and the player to send commands to: this tab's, or
 * in remote mode the one it controls (`remote`: which one; null: this tab's).
 */
export function usePlayer(): { state: PlayerSnapshot; engine: PlayerController; remote: RemotePlayer | null } {
  const { active, mode } = usePlayerValue();
  const state = useSyncExternalStore(active.subscribe, active.getSnapshot);
  return { state, engine: active, remote: mode.kind === "remote" ? mode : null };
}

/**
 * The player only, without following its state: for components that read the position
 * themselves (every animation frame) and must not re-render at every player tick, such
 * as the lyrics of a long audiobook.
 */
export function usePlayerEngine(): PlayerController {
  return usePlayerValue().active;
}

/** This tab's own player, whatever the UI drives (settings, being controlled...). */
export function useLocalPlayer(): PlayerEngine {
  return usePlayerValue().local;
}

/**
 * Remote mode: the remote player follows the target chosen in the Remote menu, and this
 * tab's own player is paused (left as it was, for when it plays here again). The target
 * gone (tab closed, server restarted): back to this tab, with a notice.
 *
 * This tab's own TV page ("screen": cast/tv) is driven through its own link, and its queue
 * came from here: leaving it, the queue comes back here, where it was (playing if it was).
 */
function useRemoteMode(engine: PlayerEngine, mode: PlayerMode): RemoteController {
  const remote = useMemo(() => new RemoteController(remoteLink), []);
  const screen = useMemo(() => new RemoteController(screenLink), []);
  const onScreen = mode.kind === "remote" && mode.targetKind === "screen";
  const target = mode.kind === "remote" ? mode.target : null;
  const name = mode.kind === "remote" ? mode.name : "";
  useEffect(() => {
    const controller = onScreen ? screen : remote;
    const link = onScreen ? screenLink : remoteLink;
    controller.connect(target);
    if (!target) return;
    engine.pause();
    const check = () => {
      const { targets } = link.getView();
      if (targets && !targets.some((t) => t.id === target)) playHere(`${name} can no longer be controlled`);
    };
    const unsubscribe = link.subscribe(check);
    return () => {
      unsubscribe();
      controller.connect(null);
      if (onScreen && target === SCREEN_TARGET) {
        const back = screenLink.takeBack();
        screenLink.stop();
        if (back && back.queue.tracks.length) {
          engine.restoreQueue(back.queue);
          if (back.playing) engine.togglePlay();
        }
      }
    };
  }, [remote, screen, engine, onScreen, target, name]);
  return onScreen ? screen : remote;
}

/**
 * Crossfade settings follow the user (server preferences): applied to the engine once
 * loaded, and saved when changed from the player bar or the Account page. Volume,
 * shuffle and repeat stay per browser.
 */
function useSyncedPlayerPreferences(engine: PlayerEngine): void {
  const { preferences, update } = usePreferences();
  const state = useSyncExternalStore(engine.subscribe, engine.getSnapshot);

  const saved = preferences?.player;
  useEffect(() => {
    if (!saved) return;
    engine.setCrossfade(saved.crossfade);
    engine.setCrossfadeSeconds(saved.crossfadeSeconds);
    engine.setSpokenSpeed(saved.spokenSpeed ?? 1);
  }, [engine, saved]);

  // Before the preferences are loaded `update` does nothing: the server values win.
  useEffect(() => {
    update((current) => {
      const { crossfade, crossfadeSeconds } = current.player;
      if (state.crossfade === crossfade && state.crossfadeSeconds === crossfadeSeconds) return current;
      return {
        ...current,
        player: { ...current.player, crossfade: state.crossfade, crossfadeSeconds: state.crossfadeSeconds },
      };
    });
  }, [state.crossfade, state.crossfadeSeconds, update]);
}

const NOTICE_MS = 12000;

/**
 * Audiobooks and podcasts: their position is saved as a bookmark (every few seconds, on
 * pause, on track change, when the page closes) and they resume there when played again.
 *
 * Followed across devices (see services/bookmarks.py): the latest bookmark of the book is
 * checked when it becomes the current track, every CHECK_EVERY_MS, when the tab is back in
 * front and when it starts playing here. When another device moved it, this player moves
 * there: paused, it stays paused; playing, it pauses (the other device took over), unless
 * it just started playing here, then it takes over (it moves there and plays on). Saves
 * say which bookmark they follow: one made from an outdated position is refused.
 */
function useBookmarks(engine: PlayerEngine): ResumeValue {
  const [notice, setNotice] = useState<ResumeNotice | null>(null);
  // The latest bookmark this tab knows, of the current track's book.
  const seen = useRef<{ book: string; changedAt: string | null } | null>(null);
  // Saves in flight, and answered: a check answered meanwhile may be about our own save.
  const saving = useRef(0);
  const answered = useRef(0);
  // The track that started from its beginning (the keeper's `resume`): resumed when known.
  const resumeWanted = useRef<string | null>(null);
  const before = useRef<QueueState | null>(null); // for "Undo"
  const keeperRef = useRef<ReturnType<typeof createBookmarkKeeper> | null>(null);
  const source = useMemo(() => deviceName(), []);

  const seenFor = useCallback(
    (track: Track) => (seen.current?.book === bookOf(track) ? seen.current.changedAt : null),
    [],
  );
  const know = useCallback((track: Track, bookmark: SyncedBookmark | null) => {
    seen.current = { book: bookOf(track), changedAt: bookmark?.changedAt ?? null };
  }, []);

  /** To where another device left the current book: `follow` (it moved there), or
   * `takeOver` (playback just started here: it plays on there). */
  const moveTo = useCallback(
    (bookmark: SyncedBookmark, how: "follow" | "takeOver") => {
      const state = engine.getSnapshot();
      const current = state.current;
      if (!current?.longForm) return;
      seen.current = { book: bookOf(current), changedAt: bookmark.changedAt };
      const move = moveFor(bookmark, current, engine.currentTime, state.queue, state.index);
      if (move.kind === "none") return;
      const wasPlaying = state.playing;
      before.current = engine.exportQueue();
      keeperRef.current?.forget(); // what this player had is not saved over it
      if (wasPlaying && how === "follow") engine.pause();
      const shown: ResumeNotice = {
        trackId: move.kind === "seek" ? current.id : bookmark.songId,
        seconds: move.seconds,
        from: { source: bookmark.source, changedAt: bookmark.changedAt, tookOver: wasPlaying && how === "follow" },
      };
      const restore = (queue: QueueState) => {
        engine.restoreQueue(queue);
        if (how === "takeOver" && wasPlaying) engine.togglePlay();
      };
      if (move.kind === "seek") engine.seek(move.seconds);
      else if (move.kind === "queue") restore({ ...engine.exportQueue(), index: move.index, position: move.seconds });
      else {
        // Not queued: the book from that file on, as its page plays it.
        if (!current.albumId) return;
        void api
          .getSpokenShow(current.albumId)
          .then(({ episodes }) => {
            const from = episodes.findIndex((e) => e.id === move.songId);
            if (from < 0) return;
            const tracks = episodes.slice(from).map(songToTrack);
            const shuffled = engine.getSnapshot().shuffle; // the music's shuffle setting stays
            restore({ tracks, originalOrder: shuffled ? tracks.map((_, i) => i) : null, index: 0, position: move.seconds });
            setNotice(shown);
          })
          .catch(() => undefined);
        return;
      }
      setNotice(shown);
    },
    [engine],
  );

  /** After a save or a removal: known, or refused (another device moved on: follow it). */
  const settle = useCallback(
    (track: Track, request: Promise<CheckedBookmark>) => {
      saving.current++;
      void request
        .then((result) => {
          if (result.saved) know(track, result.bookmark);
          else if (result.bookmark && sameBook(engine, track)) moveTo(result.bookmark, "follow");
        })
        .catch(() => undefined)
        .finally(() => {
          saving.current--;
          answered.current++;
        });
    },
    [engine, know, moveTo],
  );

  const save = useCallback(
    (track: Track, seconds: number, keepalive?: boolean) =>
      settle(
        track,
        api.saveBookmark(track.id, { positionMs: Math.round(seconds * 1000), seen: seenFor(track), source }, keepalive),
      ),
    [settle, seenFor, source],
  );

  /** Playing here (just started): this device has the book now. */
  const claim = useCallback(() => {
    const state = engine.getSnapshot();
    if (state.current?.longForm && state.playing) save(state.current, Math.max(engine.currentTime, 0));
  }, [engine, save]);

  const keeper = useMemo(
    () =>
      createBookmarkKeeper({
        save,
        remove: (track, keepalive) => settle(track, api.removeBookmark(track.id, seenFor(track), keepalive)),
        // Became current: the latest bookmark of its book, then resume or move there.
        started: (track) => {
          resumeWanted.current = null;
          const { playing, positioned } = engine.getSnapshot();
          void api
            .getLatestBookmark(track.id, null)
            .then(({ bookmark }) => {
              if (engine.getSnapshot().current?.id !== track.id) return;
              know(track, bookmark);
              if (bookmark?.songId === track.id) {
                if (resumeWanted.current === track.id) resumeAt(engine, track, bookmark, setNotice);
              } else if (bookmark && !playing && !positioned) {
                // In another file of the book, and this one was not chosen (a restored queue).
                moveTo(bookmark, "follow");
              }
              claim();
            })
            .catch(() => undefined);
        },
        resume: (track) => {
          resumeWanted.current = track.id;
        },
      }),
    [engine, save, settle, seenFor, know, moveTo, claim],
  );
  keeperRef.current = keeper;

  /** Has another device moved the current book's bookmark? (`takeOver`: just started here.) */
  const check = useCallback(
    (how: "follow" | "takeOver") => {
      const current = engine.getSnapshot().current;
      if (!current?.longForm || saving.current > 0 || seen.current?.book !== bookOf(current)) return;
      const asked = answered.current;
      void api
        .getLatestBookmark(current.id, seen.current.changedAt)
        .then(({ bookmark, moved }) => {
          if (answered.current !== asked || saving.current > 0) return; // maybe our own save
          if (engine.getSnapshot().current?.id !== current.id) return;
          if (moved && bookmark) moveTo(bookmark, how);
          if (how === "takeOver") claim();
        })
        .catch(() => undefined);
    },
    [engine, moveTo, claim],
  );

  const state = useSyncExternalStore(engine.subscribe, engine.getSnapshot);
  useEffect(() => keeper.update(state), [keeper, state]);
  useEffect(() => {
    const leave = () => keeper.leave();
    window.addEventListener("pagehide", leave);
    return () => window.removeEventListener("pagehide", leave);
  }, [keeper]);
  // Every 30 s (hidden too: it may be playing in the background), and back in front.
  useEffect(() => {
    const follow = () => check("follow");
    const onVisible = () => document.visibilityState === "visible" && follow();
    const timer = window.setInterval(follow, CHECK_EVERY_MS);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", follow);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", follow);
    };
  }, [check]);
  // Started playing here: from where the book is now, and this device has it.
  const playing = state.playing;
  useEffect(() => {
    if (playing) check("takeOver");
  }, [playing, check]);
  // The notice goes after a while, or with its track.
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice]);
  const currentId = state.current?.id;
  useEffect(() => {
    if (notice && currentId !== notice.trackId) setNotice(null);
  }, [currentId, notice]);

  const startOver = useCallback(() => {
    engine.seek(0);
    setNotice(null);
  }, [engine]);
  // Back to where this player was (it then saves from there: the user chose it).
  const undo = useCallback(() => {
    const queue = before.current;
    before.current = null;
    setNotice(null);
    if (!queue) return;
    keeperRef.current?.forget();
    engine.restoreQueue(queue);
  }, [engine]);
  const dismiss = useCallback(() => setNotice(null), []);
  return useMemo(() => ({ notice, startOver, undo, dismiss }), [notice, startOver, undo, dismiss]);
}

/** `track` is of the current track's book. */
function sameBook(engine: PlayerEngine, track: Track): boolean {
  const current = engine.getSnapshot().current;
  return current !== null && bookOf(current) === bookOf(track);
}

/** Started from its beginning: at its bookmark, when worth it ("Resumed at 12:34"). */
function resumeAt(engine: PlayerEngine, track: Track, bookmark: SyncedBookmark, notify: (notice: ResumeNotice) => void) {
  const seconds = bookmark.positionMs / 1000;
  const duration = track.durationSeconds ?? 0;
  if (engine.currentTime >= STARTED_S) return;
  if (seconds < RESUME_FROM_S || (duration && seconds >= duration - FINISHED_S)) return;
  engine.seek(seconds);
  notify({ trackId: track.id, seconds });
}

/** Space: play / pause; ← / →: 10 s back / forward (see shortcuts.ts for when they apply). */
function useShortcuts(engine: PlayerController): void {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const action = shortcutFor(event);
      const state = engine.getSnapshot();
      if (!action || !state.current) return;
      event.preventDefault(); // no page scroll on Space / arrows
      if (action === "toggle") engine.togglePlay();
      else {
        const target = engine.currentTime + (action === "back" ? -SEEK_STEP_S : SEEK_STEP_S);
        engine.seek(Math.min(Math.max(target, 0), Math.max(state.duration - 0.5, 0)));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [engine]);
}

/** The visualizers' AudioContext runs while playing (also after the tab slept), and only then. */
function useAudioResume(engine: PlayerEngine): void {
  const playing = useSyncExternalStore(engine.subscribe, () => engine.getSnapshot().playing);
  useEffect(() => {
    if (playing) resumeAudio();
    else suspendAudio();
  }, [playing]);
}

/** Reports plays to the server (Subsonic `scrobble`): play counts, recently played. */
function useScrobbling(engine: PlayerEngine, client: SubsonicClient): void {
  const clientRef = useRef(client);
  clientRef.current = client;
  const feed = useMemo(
    () =>
      createScrobbler({
        nowPlaying: (id) => void clientRef.current.call("scrobble", { id, submission: "false" }).catch(() => undefined),
        played: (id, startedAt) =>
          void clientRef.current
            .call("scrobble", { id, submission: "true", time: String(startedAt) })
            .catch(() => undefined),
      }),
    [],
  );
  const state = useSyncExternalStore(engine.subscribe, engine.getSnapshot);
  useEffect(() => {
    feed({
      key: state.index >= 0 ? (state.keys[state.index] ?? null) : null,
      trackId: state.current?.id ?? null,
      playing: state.playing,
      position: state.position,
      duration: state.duration,
    });
  }, [feed, state]);
}

// Audiobooks and podcasts: the lock screen's skip buttons (as the player bar's −15 / +30).
const SKIP_BACK_S = 15;
const SKIP_FORWARD_S = 30;

/** OS integration: media keys, lock screen / notification controls. */
function useMediaSession(engine: PlayerEngine, client: SubsonicClient): void {
  const state = useSyncExternalStore(engine.subscribe, engine.getSnapshot);
  const current = state.current;
  const spoken = state.spoken;
  const chapterTitle = current?.chapters?.[state.chapter]?.title;

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    const handlers: [MediaSessionAction, MediaSessionActionHandler][] = [
      // Not toggles: a "pause" sent while already paused (the OS may) must not play.
      ["play", () => !engine.getSnapshot().playing && engine.togglePlay()],
      ["pause", () => engine.pause()],
      ["previoustrack", () => engine.previous()],
      ["nexttrack", () => engine.next()],
      ["seekto", (details) => details.seekTime !== undefined && engine.seek(details.seekTime)],
    ];
    for (const [action, handler] of handlers) {
      try {
        navigator.mediaSession.setActionHandler(action, handler);
      } catch {
        // action not supported by this browser
      }
    }
  }, [engine]);

  // Audiobooks and podcasts: skip buttons (iOS then shows them instead of previous / next).
  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    const skip = (seconds: number) => () => {
      const duration = engine.getSnapshot().duration;
      engine.seek(Math.min(Math.max(engine.currentTime + seconds, 0), Math.max(duration - 0.5, 0)));
    };
    const handlers: [MediaSessionAction, MediaSessionActionHandler | null][] = [
      ["seekbackward", spoken ? skip(-SKIP_BACK_S) : null],
      ["seekforward", spoken ? skip(SKIP_FORWARD_S) : null],
    ];
    for (const [action, handler] of handlers) {
      try {
        navigator.mediaSession.setActionHandler(action, handler);
      } catch {
        // action not supported by this browser
      }
    }
  }, [engine, spoken]);

  // The lock screen's progress bar (and scrubbing, "seekto").
  const duration = state.duration;
  const position = Math.floor(state.position);
  useEffect(() => {
    if (!("mediaSession" in navigator) || !navigator.mediaSession.setPositionState) return;
    try {
      navigator.mediaSession.setPositionState(
        duration > 0
          ? { duration, position: Math.min(position, duration), playbackRate: engine.playbackRate }
          : undefined,
      );
    } catch {
      // an inconsistent state (e.g. while a new file loads): the next update fixes it
    }
  }, [engine, duration, position]);

  useEffect(() => {
    if (!("mediaSession" in navigator) || typeof MediaMetadata === "undefined") return;
    navigator.mediaSession.metadata = current
      ? new MediaMetadata({
          title: current.title,
          // An audiobook's chapter inside the file, before its author.
          artist: chapterTitle ? `${chapterTitle} · ${current.artist ?? ""}` : (current.artist ?? ""),
          album: current.album ?? "",
          artwork: current.coverArt
            ? [
                {
                  src: client.url("getCoverArt", { id: current.coverArt, size: 512, ...coverVersion(current.coverArt) }),
                  sizes: "512x512",
                },
              ]
            : [],
        })
      : null;
  }, [client, current, chapterTitle]);

  useEffect(() => {
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = state.playing ? "playing" : "paused";
  }, [state.playing]);
}
