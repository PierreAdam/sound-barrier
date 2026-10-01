import { useEffect, useRef } from "react";

import { api } from "../api/native";
import { useSession } from "../auth/AuthContext";
import { SCREEN_TARGET, screenLink } from "../cast/tv/screenLink";
import { useLocalPlayer } from "../player/PlayerContext";
import type { PlayerEngine } from "../player/engine";
import { useWebPlayerId } from "../player/webPlayer";
import { usePreferences } from "../preferences/PreferencesContext";
import { applyCommand } from "./apply";
import { usePlayerMode } from "./mode";
import { deviceName, type RemoteCommand } from "./protocol";
import { createReporter, type Reports } from "./reporter";
import { RemoteSocket } from "./socket";
import { consumeTakeOver, getRemoteTarget, setRemoteTarget, useRemoteTarget } from "./target";

/** What the user's other devices control through this tab: reported to them, commanded. */
interface Source {
  report(force?: boolean): void;
  apply(command: RemoteCommand): void;
  stop(): void;
}

/** This tab's own player, as if its own controls were used. */
function localSource(engine: PlayerEngine, send: Reports, ready: () => boolean, setSpeed: (speed: number) => void): Source {
  const reporter = createReporter(engine, send, ready);
  const stop = reporter.follow();
  return { report: reporter.report, apply: (command) => applyCommand(engine, command, setSpeed), stop };
}

/**
 * The TV page this tab drives (cast/tv): it speaks the remote control's protocol, so its
 * reports go on to the other devices as they are, and their commands go to it.
 */
function screenSource(send: Reports, ready: () => boolean): Source {
  const report = (force = false) => {
    if (!force || !ready()) return;
    const { queue, state } = screenLink.latest();
    if (queue) send.queue(queue); // first: the state names the queue it goes with
    if (state) send.state(state);
  };
  const stop = screenLink.onReport((message) => {
    if (!ready()) return;
    if (message.type === "queue") send.queue(message.queue);
    else send.state(message.state);
  });
  return { report, apply: (command) => screenLink.send(SCREEN_TARGET, command), stop };
}

/**
 * While this tab is controllable (queue panel, Remote menu): its player is reported to the
 * user's remotes (the queue too, to those mirroring it), and their commands applied as if
 * its own controls were used. While it drives its TV page, that is the TV page's player:
 * the other devices control the TV through this tab (the same entry for them, on the TV or
 * back here). Nothing else of the app knows about it.
 */
export function RemoteTargetBridge() {
  const status = useRemoteTarget();
  const wanted = status.kind === "connecting" || status.kind === "on";
  const engine = useLocalPlayer();
  const { username } = useSession().user;
  const playerId = useWebPlayerId(username);
  const { update } = usePreferences();
  const mode = usePlayerMode();
  const onScreen = mode.kind === "remote" && mode.target === SCREEN_TARGET;
  // Read by the connection's callbacks (set up once per connection).
  const live = useRef({ playerId, update, onScreen });
  live.current = { playerId, update, onScreen };
  const register = useRef(() => undefined as void);
  const socketRef = useRef<RemoteSocket | null>(null);
  const source = useRef<Source | null>(null);

  // The connection: kept while controllable (whatever it controls: its id stays).
  useEffect(() => {
    if (!wanted) return;
    const registerTarget = async () => {
      const id = live.current.playerId;
      let playerName = "Shared";
      if (id) {
        const players = await api.getPlayers().catch(() => null);
        playerName = players?.players.find((player) => player.id === id)?.name ?? "A player";
      }
      const device = live.current.onScreen ? `${deviceName()} (on the TV)` : deviceName();
      socket.send({ type: "target", player: id, playerName, device, takeOver: consumeTakeOver() });
    };

    const socket = new RemoteSocket({
      open: () => void registerTarget(),
      message: (message) => {
        switch (message.type) {
          case "target-on":
            setRemoteTarget({ kind: "on", id: message.id });
            source.current?.report(true);
            break;
          case "conflict":
            setRemoteTarget({ kind: "conflict", device: message.device });
            break;
          case "replaced":
            setRemoteTarget({ kind: "replaced", device: message.device });
            break;
          case "command":
            source.current?.apply(message.command);
            break;
        }
      },
      connected: (connected) => {
        // Reconnecting: registered again once connected.
        if (!connected && getRemoteTarget().kind === "on") setRemoteTarget({ kind: "connecting" });
      },
    });
    socketRef.current = socket;
    register.current = () => void registerTarget();
    socket.start();
    return () => {
      socket.send({ type: "stop" });
      socket.stop();
      socketRef.current = null;
      register.current = () => undefined;
    };
  }, [wanted]);

  // What it controls: this tab's player, or its TV page. Switched without reconnecting.
  useEffect(() => {
    const socket = socketRef.current;
    if (!wanted || !socket) return;
    const send: Reports = {
      queue: (queue) => socket.send({ type: "queue", queue }),
      state: (state) => socket.send({ type: "state", state }),
    };
    const ready = () => getRemoteTarget().kind === "on" && socket.connected;
    const setSpeed = (speed: number) =>
      live.current.update((current) => ({ ...current, player: { ...current.player, spokenSpeed: speed } }));
    const current = onScreen ? screenSource(send, ready) : localSource(engine, send, ready, setSpeed);
    source.current = current;
    current.report(true); // the other devices see what it is now
    // Its device line: "(on the TV)" or not (when not connected yet, it registers on opening).
    if (socket.connected) register.current();
    return () => {
      current.stop();
      if (source.current === current) source.current = null;
    };
  }, [wanted, engine, onScreen]);

  // This browser switched player: controllable as that one (or told it is taken).
  useEffect(() => {
    register.current();
  }, [playerId]);

  return null;
}
