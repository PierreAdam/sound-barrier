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

import { coverVersion } from "../api/coverVersions";
import type { SubsonicClient } from "../api/subsonic";
import { useSession } from "../auth/AuthContext";
import { usePreferences } from "../preferences/PreferencesContext";
import { SCREEN_TARGET, screenLink } from "../cast/tv/screenLink";
import { remoteLink } from "../remote/link";
import { type PlayerMode, playHere, usePlayerMode } from "../remote/mode";
import { RemoteController } from "../remote/RemoteController";
import { resumeAudio } from "./audioGraph";
import { createBookmarkKeeper, RESUME_FROM_S, FINISHED_S, STARTED_S } from "./bookmarks";
import type { PlayerController } from "./controller";
import { PlayerEngine, type PlayerSnapshot } from "./engine";
import { createScrobbler } from "./scrobble";
import { SEEK_STEP_S, shortcutFor } from "./shortcuts";
import { useWebQueue } from "./useWebQueue";

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

/** "Resumed at 12:34": shown by the player bar after an audiobook / podcast resumed. */
export interface ResumeNotice {
  trackId: string;
  seconds: number;
}

interface ResumeValue {
  notice: ResumeNotice | null;
  startOver(): void;
  dismiss(): void;
}

const ResumeContext = createContext<ResumeValue>({ notice: null, startOver: () => undefined, dismiss: () => undefined });

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
  const resume = useBookmarks(engine, client);
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
 */
function useBookmarks(engine: PlayerEngine, client: SubsonicClient): ResumeValue {
  const clientRef = useRef(client);
  clientRef.current = client;
  const [notice, setNotice] = useState<ResumeNotice | null>(null);
  const keeper = useMemo(
    () =>
      createBookmarkKeeper({
        save: (track, seconds, keepalive) =>
          void clientRef.current
            .call("createBookmark", { id: track.id, position: String(Math.round(seconds * 1000)) }, { keepalive })
            .catch(() => undefined),
        remove: (track, keepalive) =>
          void clientRef.current.call("deleteBookmark", { id: track.id }, { keepalive }).catch(() => undefined),
        // The latest bookmark (another device may have moved it), then resume if still at the start.
        resume: (track) =>
          void clientRef.current
            .call("getSong", { id: track.id })
            .then(({ song }) => {
              const seconds = (song.bookmarkPosition ?? 0) / 1000;
              const duration = song.duration ?? track.durationSeconds ?? 0;
              const current = engine.getSnapshot();
              if (current.current?.id !== track.id || engine.currentTime >= STARTED_S) return;
              if (seconds < RESUME_FROM_S || (duration && seconds >= duration - FINISHED_S)) return;
              engine.seek(seconds);
              setNotice({ trackId: track.id, seconds });
            })
            .catch(() => undefined),
      }),
    [engine],
  );
  const state = useSyncExternalStore(engine.subscribe, engine.getSnapshot);
  useEffect(() => keeper.update(state), [keeper, state]);
  useEffect(() => {
    const leave = () => keeper.leave();
    window.addEventListener("pagehide", leave);
    return () => window.removeEventListener("pagehide", leave);
  }, [keeper]);
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
  const dismiss = useCallback(() => setNotice(null), []);
  return useMemo(() => ({ notice, startOver, dismiss }), [notice, startOver, dismiss]);
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

/** Playing again after the tab slept: the visualizers' AudioContext must run too. */
function useAudioResume(engine: PlayerEngine): void {
  const playing = useSyncExternalStore(engine.subscribe, () => engine.getSnapshot().playing);
  useEffect(() => {
    if (playing) resumeAudio();
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
      ["play", () => engine.togglePlay()],
      ["pause", () => engine.togglePlay()],
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
