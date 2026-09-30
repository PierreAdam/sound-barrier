import { useEffect, useRef } from "react";

import { api } from "../api/native";
import { useSession } from "../auth/AuthContext";
import { useLocalPlayer } from "../player/PlayerContext";
import { useWebPlayerId } from "../player/webPlayer";
import { usePreferences } from "../preferences/PreferencesContext";
import { applyCommand, remoteStateOf } from "./apply";
import { deviceName } from "./protocol";
import { RemoteSocket } from "./socket";
import { consumeTakeOver, getRemoteTarget, setRemoteTarget, useRemoteTarget } from "./target";

// A state is sent when something changes, and this often while playing (keeps the
// remotes' clocks right).
const HEARTBEAT_MS = 10_000;
// The position is sent again when it moved this far from where remotes expect it (a seek).
const JUMP_SECONDS = 1.5;

/**
 * While this tab is controllable (queue panel, Remote menu): its player is reported to the
 * user's remotes (the queue too, to those mirroring it), and their commands applied as if
 * its own controls were used. Nothing else of the app knows about it.
 */
export function RemoteTargetBridge() {
  const status = useRemoteTarget();
  const wanted = status.kind === "connecting" || status.kind === "on";
  const engine = useLocalPlayer();
  const { username } = useSession().user;
  const playerId = useWebPlayerId(username);
  const { update } = usePreferences();
  // Read by the connection's callbacks (set up once per connection).
  const live = useRef({ playerId, update });
  live.current = { playerId, update };
  const register = useRef(() => undefined as void);

  useEffect(() => {
    if (!wanted) return;
    let sent: { signature: string; position: number; at: number; playing: boolean; rate: number } | null = null;
    // The queue: sent again when its entries change (not their metadata: a key is one track).
    let queueSignature = "";
    let queueRevision = 0;

    const sendQueue = (force = false) => {
      if (getRemoteTarget().kind !== "on" || !socket.connected) return;
      const { keys, queue } = engine.getSnapshot();
      const signature = keys.join(",");
      if (!force && signature === queueSignature) return;
      if (signature !== queueSignature) queueRevision += 1;
      queueSignature = signature;
      socket.send({ type: "queue", queue: { revision: queueRevision, keys, tracks: queue } });
    };

    const sendState = (force = false) => {
      if (getRemoteTarget().kind !== "on" || !socket.connected) return;
      sendQueue(); // first: the state names the queue it goes with
      const state = remoteStateOf(engine.getSnapshot(), engine, queueRevision);
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

    const registerTarget = async () => {
      const id = live.current.playerId;
      let playerName = "Shared";
      if (id) {
        const players = await api.getPlayers().catch(() => null);
        playerName = players?.players.find((player) => player.id === id)?.name ?? "A player";
      }
      socket.send({ type: "target", player: id, playerName, device: deviceName(), takeOver: consumeTakeOver() });
    };

    const setSpeed = (speed: number) =>
      live.current.update((current) => ({ ...current, player: { ...current.player, spokenSpeed: speed } }));

    const socket = new RemoteSocket({
      open: () => void registerTarget(),
      message: (message) => {
        switch (message.type) {
          case "target-on":
            setRemoteTarget({ kind: "on", id: message.id });
            sendQueue(true);
            sendState(true);
            break;
          case "conflict":
            setRemoteTarget({ kind: "conflict", device: message.device });
            break;
          case "replaced":
            setRemoteTarget({ kind: "replaced", device: message.device });
            break;
          case "command":
            applyCommand(engine, message.command, setSpeed);
            break;
        }
      },
      connected: (connected) => {
        // Reconnecting: registered again once connected.
        if (!connected && getRemoteTarget().kind === "on") setRemoteTarget({ kind: "connecting" });
      },
    });
    register.current = () => void registerTarget();
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
      register.current = () => undefined;
    };
  }, [wanted, engine]);

  // This browser switched player: controllable as that one (or told it is taken).
  useEffect(() => {
    register.current();
  }, [playerId]);

  return null;
}
