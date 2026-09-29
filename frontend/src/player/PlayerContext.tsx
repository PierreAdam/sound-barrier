import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
} from "react";

import type { SubsonicClient } from "../api/subsonic";
import { useSession } from "../auth/AuthContext";
import { usePreferences } from "../preferences/PreferencesContext";
import { resumeAudio } from "./audioGraph";
import { PlayerEngine, type PlayerSnapshot } from "./engine";
import { createScrobbler } from "./scrobble";
import { useWebQueue } from "./useWebQueue";

export type { Track } from "./engine";
export { songToTrack } from "./tracks";

const PlayerContext = createContext<PlayerEngine | null>(null);

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
  useEffect(() => () => engine.destroy(), [engine]);
  useMediaSession(engine, client);
  useSyncedPlayerPreferences(engine);
  useWebQueue(engine);
  useScrobbling(engine, client);
  useAudioResume(engine);
  return <PlayerContext.Provider value={engine}>{children}</PlayerContext.Provider>;
}

/** Player state (re-renders on change) and the engine to send commands to. */
export function usePlayer(): { state: PlayerSnapshot; engine: PlayerEngine } {
  const engine = useContext(PlayerContext);
  if (!engine) throw new Error("usePlayer must be used inside <PlayerProvider>");
  const state = useSyncExternalStore(engine.subscribe, engine.getSnapshot);
  return { state, engine };
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
  }, [engine, saved]);

  // Before the preferences are loaded `update` does nothing: the server values win.
  useEffect(() => {
    update((current) => {
      const { crossfade, crossfadeSeconds } = current.player;
      if (state.crossfade === crossfade && state.crossfadeSeconds === crossfadeSeconds) return current;
      return { ...current, player: { crossfade: state.crossfade, crossfadeSeconds: state.crossfadeSeconds } };
    });
  }, [state.crossfade, state.crossfadeSeconds, update]);
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

/** OS integration: media keys, lock screen / notification controls. */
function useMediaSession(engine: PlayerEngine, client: SubsonicClient): void {
  const state = useSyncExternalStore(engine.subscribe, engine.getSnapshot);
  const current = state.current;

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

  useEffect(() => {
    if (!("mediaSession" in navigator) || typeof MediaMetadata === "undefined") return;
    navigator.mediaSession.metadata = current
      ? new MediaMetadata({
          title: current.title,
          artist: current.artist ?? "",
          album: current.album ?? "",
          artwork: current.coverArt
            ? [{ src: client.url("getCoverArt", { id: current.coverArt, size: 512 }), sizes: "512x512" }]
            : [],
        })
      : null;
  }, [client, current]);

  useEffect(() => {
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = state.playing ? "playing" : "paused";
  }, [state.playing]);
}
