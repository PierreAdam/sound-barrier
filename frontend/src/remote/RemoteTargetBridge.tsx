import { useEffect, useRef } from "react";

import { api } from "../api/native";
import { useSession } from "../auth/AuthContext";
import { pauseAtEndLabel, SPEEDS } from "../components/PlayerBar";
import type { PlayerEngine, PlayerSnapshot } from "../player/engine";
import { usePlayerEngine } from "../player/PlayerContext";
import { useWebPlayerId } from "../player/webPlayer";
import { usePreferences } from "../preferences/PreferencesContext";
import { deviceName, type RemoteCommand, type RemoteState } from "./protocol";
import { RemoteSocket } from "./socket";
import { consumeTakeOver, getRemoteTarget, setRemoteTarget, useRemoteTarget } from "./target";

// A state is sent when something changes, and this often while playing (keeps the
// remotes' clocks right).
const HEARTBEAT_MS = 10_000;
// The position is sent again when it moved this far from where remotes expect it (a seek).
const JUMP_SECONDS = 1.5;

function stateOf(state: PlayerSnapshot, engine: PlayerEngine, speed: number): RemoteState {
  const { current } = state;
  return {
    track: current && {
      id: current.id,
      title: current.title,
      artist: current.artist ?? null,
      album: current.album ?? null,
      coverArt: current.coverArt ?? null,
      chapter: current.chapters?.[state.chapter]?.title ?? null,
    },
    playing: state.playing,
    position: state.position,
    rate: engine.playbackRate,
    duration: state.duration,
    volume: state.volume,
    muted: state.muted,
    shuffle: state.shuffle,
    repeat: state.repeat,
    crossfade: state.crossfade,
    spoken: state.spoken,
    chapters: Boolean(current?.chapters?.length),
    pauseAtEnd: state.pauseAtEnd,
    pauseAtEndLabel: pauseAtEndLabel(current),
    speed,
    hasPrevious: state.hasPrevious,
    hasNext: state.hasNext,
    index: state.index,
    count: state.queue.length,
  };
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

/**
 * While remote control is on (queue panel): this tab's player is reported to the user's
 * remotes, and their commands applied as if its own buttons were clicked. Nothing else
 * of the app knows about it.
 */
export function RemoteTargetBridge() {
  const status = useRemoteTarget();
  const wanted = status.kind === "connecting" || status.kind === "on";
  const engine = usePlayerEngine();
  const { username } = useSession().user;
  const playerId = useWebPlayerId(username);
  const { preferences, update } = usePreferences();
  const speed = preferences?.player.spokenSpeed ?? 1;
  // Read by the connection's callbacks (set up once per connection).
  const live = useRef({ playerId, speed, update });
  live.current = { playerId, speed, update };
  const actions = useRef({ register: () => undefined as void, sendState: (_force?: boolean) => undefined as void });

  useEffect(() => {
    if (!wanted) return;
    let sent: { signature: string; position: number; at: number; playing: boolean; rate: number } | null = null;

    const sendState = (force = false) => {
      if (getRemoteTarget().kind !== "on" || !socket.connected) return;
      const state = stateOf(engine.getSnapshot(), engine, live.current.speed);
      const signature = JSON.stringify({ ...state, position: 0, rate: 0 });
      const now = Date.now();
      const expected = sent
        ? sent.position + (sent.playing ? ((now - sent.at) / 1000) * sent.rate : 0)
        : state.position;
      const jumped = Math.abs(state.position - expected) > JUMP_SECONDS;
      if (!force && sent && signature === sent.signature && !jumped) return;
      sent = { signature, position: state.position, at: now, playing: state.playing, rate: state.rate };
      socket.send({ type: "state", state });
    };

    const register = async () => {
      const id = live.current.playerId;
      let playerName = "Shared";
      if (id) {
        const players = await api.getPlayers().catch(() => null);
        playerName = players?.players.find((player) => player.id === id)?.name ?? "A player";
      }
      socket.send({ type: "target", player: id, playerName, device: deviceName(), takeOver: consumeTakeOver() });
    };

    const apply = (command: RemoteCommand) => {
      const state = engine.getSnapshot();
      switch (command.name) {
        case "toggle":
          engine.togglePlay();
          break;
        case "play":
          if (!state.playing) engine.togglePlay();
          break;
        case "pause":
          engine.pause();
          break;
        case "previous":
          engine.previous();
          break;
        case "next":
          engine.next();
          break;
        case "seek":
          if (Number.isFinite(command.position))
            engine.seek(clamp(command.position, 0, Math.max(state.duration - 0.5, 0)));
          break;
        case "skip":
          if (Number.isFinite(command.seconds))
            engine.seek(clamp(engine.currentTime + command.seconds, 0, Math.max(state.duration - 0.5, 0)));
          break;
        case "volume":
          if (Number.isFinite(command.value)) engine.setVolume(clamp(command.value, 0, 1));
          break;
        case "mute":
          engine.toggleMute();
          break;
        // As on the player bar: not for audiobooks and podcasts...
        case "shuffle":
          if (!state.spoken) engine.toggleShuffle();
          break;
        case "repeat":
          if (!state.spoken) engine.cycleRepeat();
          break;
        case "crossfade":
          if (!state.spoken) engine.toggleCrossfade();
          break;
        // ...and only for them.
        case "pauseAtEnd":
          if (state.spoken) engine.setPauseAtEnd(!state.pauseAtEnd);
          break;
        case "speed":
          if (state.spoken && SPEEDS.includes(command.value))
            live.current.update((current) => ({ ...current, player: { ...current.player, spokenSpeed: command.value } }));
          break;
      }
    };

    const socket = new RemoteSocket({
      open: () => void register(),
      message: (message) => {
        switch (message.type) {
          case "target-on":
            setRemoteTarget({ kind: "on" });
            sendState(true);
            break;
          case "conflict":
            setRemoteTarget({ kind: "conflict", device: message.device });
            break;
          case "replaced":
            setRemoteTarget({ kind: "replaced", device: message.device });
            break;
          case "command":
            apply(message.command);
            break;
        }
      },
      connected: (connected) => {
        // Reconnecting: registered again once connected.
        if (!connected && getRemoteTarget().kind === "on") setRemoteTarget({ kind: "connecting" });
      },
    });
    actions.current = { register: () => void register(), sendState };
    socket.start();
    const unsubscribe = engine.subscribe(() => sendState());
    const heartbeat = setInterval(() => {
      if (engine.getSnapshot().playing) sendState(true);
    }, HEARTBEAT_MS);
    return () => {
      clearInterval(heartbeat);
      unsubscribe();
      socket.send({ type: "stop" });
      socket.stop();
      actions.current = { register: () => undefined, sendState: () => undefined };
    };
  }, [wanted, engine]);

  // This browser switched player: controllable as that one (or told it is taken).
  useEffect(() => {
    actions.current.register();
  }, [playerId]);

  // The speed is a preference (not the engine's): its change is sent from here.
  useEffect(() => {
    actions.current.sendState();
  }, [speed]);

  return null;
}
