import { useEffect, useRef } from "react";

import { api } from "../api/native";
import { useSession } from "../auth/AuthContext";
import { useLocalPlayer } from "../player/PlayerContext";
import { useWebPlayerId } from "../player/webPlayer";
import { usePreferences } from "../preferences/PreferencesContext";
import { applyCommand } from "./apply";
import { deviceName } from "./protocol";
import { createReporter } from "./reporter";
import { RemoteSocket } from "./socket";
import { consumeTakeOver, getRemoteTarget, setRemoteTarget, useRemoteTarget } from "./target";

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
    const reporter = createReporter(
      engine,
      {
        queue: (queue) => socket.send({ type: "queue", queue }),
        state: (state) => socket.send({ type: "state", state }),
      },
      () => getRemoteTarget().kind === "on" && socket.connected,
    );

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
            reporter.report(true);
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
    const stopFollowing = reporter.follow();
    return () => {
      stopFollowing();
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
