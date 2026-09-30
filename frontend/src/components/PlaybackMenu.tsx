import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type WebPlayer } from "../api/native";
import { useSession } from "../auth/AuthContext";
import { plural } from "../format";
import { setWebPlayerId, useWebPlayerId } from "../player/webPlayer";
import { type LinkTarget, useRemoteLink } from "../remote/link";
import { controlTarget, playHere, usePlayerMode } from "../remote/mode";
import { ServerPlayerSection } from "../remote/ServerPlayerSection";
import { disableRemoteTarget, enableRemoteTarget, getRemoteTarget, useRemoteTarget } from "../remote/target";
import { Dropdown } from "./Dropdown";
import { CheckIcon, ChevronDownIcon, DevicesIcon, RemoteIcon } from "./Icons";
import { InfoTip } from "./InfoTip";

export const SWITCH_HINT =
  "Each player keeps its own queue. Switching pauses, keeps this queue in the player it belongs to, " +
  "and brings the other player's queue here (queues are not moved from one player to another).";

/** "Server player", or "PC · Vivaldi on Windows". */
function targetName(target: LinkTarget): string {
  return target.kind === "server" ? target.playerName : `${target.playerName} · ${target.device}`;
}

/** For "Playing on …": the player's name, the device's for a tab on the Shared player. */
function shortName(target: LinkTarget): string {
  return target.kind === "browser" && target.playerName === "Shared" ? target.device : target.playerName;
}

/** A menu section's title, with its ⓘ. */
export function MenuSection({ title, info, children }: { title: string; info: string; children: React.ReactNode }) {
  return (
    <p className="dropdown__header playback-menu__section">
      <span>{title}</span>
      <InfoTip label={info}>{children}</InfoTip>
    </p>
  );
}

/**
 * Queue panel: where the player bar plays, in one menu. Here, on one of this browser's
 * players (each keeps its own queue), controllable or not by the user's other devices; or
 * on another player (remote mode: another tab, the server player).
 */
export function PlaybackMenu({ open, onNavigate }: { open: boolean; onNavigate(): void }) {
  const { username } = useSession().user;
  const playerId = useWebPlayerId(username);
  const mode = usePlayerMode();
  const controllable = useRemoteTarget();
  const [players, setPlayers] = useState<WebPlayer[] | null>(null);

  // Asked each time the queue opens: players may have been created on another device.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api
      .getPlayers()
      .then(({ players }) => !cancelled && setPlayers(players))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [open]);

  // Already controllable in another tab for the same player: only one of them can be.
  useEffect(() => {
    if (controllable.kind !== "conflict") return;
    const question = `Another tab (${controllable.device}) can already be controlled for this player. Take over?`;
    if (window.confirm(question)) enableRemoteTarget({ takeOver: true });
    else disableRemoteTarget();
  }, [controllable]);

  const queueName = playerId ? (players?.find((p) => p.id === playerId)?.name ?? "…") : "Shared";
  const on = controllable.kind === "on" || controllable.kind === "connecting";
  const remote = mode.kind === "remote";
  const name = remote ? mode.name : queueName;
  return (
    <Dropdown
      className="player-switch-menu playback-menu"
      fixed
      buttonClassName={`player-switch${remote || on || playerId ? " player-switch--own" : ""}`}
      label={remote ? `Playing on ${name}. Change` : `Playing here, player ${name}. Change`}
      button={
        <>
          {remote ? <RemoteIcon /> : <DevicesIcon />}
          <span className="player-switch__label">{remote ? "Playing on" : "Player"}</span>
          <span className="player-switch__name">{name}</span>
          {on && <RemoteIcon />}
          <ChevronDownIcon />
        </>
      }
    >
      {(close) => (
        <PlaybackChoices
          players={players}
          playerId={playerId}
          username={username}
          close={close}
          onNavigate={onNavigate}
        />
      )}
    </Dropdown>
  );
}

function PlaybackChoices({
  players,
  playerId,
  username,
  close,
  onNavigate,
}: {
  players: WebPlayer[] | null;
  playerId: string | null;
  username: string;
  close(): void;
  onNavigate(): void;
}) {
  const mode = usePlayerMode();
  const controllable = useRemoteTarget();
  const { targets, connected } = useRemoteLink(); // connected while the menu is open
  const own = controllable.kind === "on" ? controllable.id : null;
  const others = (targets ?? []).filter((t) => t.id !== own && t.kind === "browser");
  const on = controllable.kind === "on" || controllable.kind === "connecting";
  const here = mode.kind === "local";

  const item = (key: string, active: boolean, name: string, detail: string, onClick: () => void) => (
    <button
      key={key}
      className={`dropdown__item player-switch-menu__item${active ? " dropdown__item--active" : ""}`}
      type="button"
      role="menuitemradio"
      aria-checked={active}
      onClick={onClick}
    >
      <span className="player-switch-menu__check">{active && <CheckIcon />}</span>
      <span className="player-switch-menu__name">{name}</span>
      <span className="player-switch-menu__detail">{detail}</span>
    </button>
  );

  const queues: { id: string | null; name: string; detail: string }[] = [
    { id: null, name: "Shared", detail: "" },
    ...(players ?? []).map((p) => ({ id: p.id, name: p.name, detail: plural(p.songCount, "track") })),
  ];

  return (
    <>
      <MenuSection title="This browser" info="About players">
        <strong>Players</strong>: {SWITCH_HINT} Every browser without a player of its own plays the Shared one.
      </MenuSection>
      {queues.map((queue) =>
        item(queue.id ?? "shared", here && queue.id === playerId, queue.name, queue.detail, () => {
          playHere(); // back from remote mode too
          if (queue.id !== playerId) setWebPlayerId(username, queue.id);
          close();
        }),
      )}
      <div className="playback-menu__option">
        <label className="dropdown__item remote-menu__option">
          <input
            type="checkbox"
            checked={on}
            onChange={(e) => {
              if (e.target.checked) {
                playHere(); // controlling another player and being controlled: never both
                enableRemoteTarget();
              } else {
                disableRemoteTarget();
              }
            }}
          />
          <span>Let my other devices control this tab</span>
        </label>
        <InfoTip label="About remote control">
          <strong>Remote control</strong>: your other devices (a phone, another computer or tab) then list this
          tab under “Other devices”, and can play, pause, skip and change its queue. Off again when this page is
          reloaded: a reloaded page cannot start playing before it is tapped.
        </InfoTip>
      </div>
      {controllable.kind === "replaced" && (
        <p className="dropdown__header remote-menu__note">Another tab took over: {controllable.device}</p>
      )}

      <MenuSection title="Other devices" info="About controlling another device">
        <strong>Control another device</strong>: the player bar and the queue then show what it plays, and what
        you play or queue while browsing goes there. Nothing plays here meanwhile (“Play here” brings your own
        queue back). A device is listed once “Let my other devices control this tab” is on there.
      </MenuSection>
      {targets === null ? (
        <p className="dropdown__header remote-menu__note">{connected ? "Looking for your devices…" : "Connecting…"}</p>
      ) : others.length === 0 ? (
        <p className="dropdown__header remote-menu__note">None right now</p>
      ) : (
        others.map((target) => {
          const active = mode.kind === "remote" && mode.target === target.id;
          const track = target.state?.current;
          const detail = track ? `${target.state?.playing ? "▶ " : ""}${track.title}` : "nothing playing";
          return item(target.id, active, targetName(target), detail, () => {
            if (getRemoteTarget().kind !== "off") disableRemoteTarget();
            controlTarget(target.id, shortName(target), target.kind);
            close();
          });
        })
      )}

      <ServerPlayerSection
        target={(targets ?? []).find((t) => t.kind === "server") ?? null}
        active={mode.kind === "remote" && mode.targetKind === "server"}
        close={close}
      />

      <Link
        className="dropdown__item dropdown__item--separated"
        role="menuitem"
        to="/account#players"
        onClick={() => {
          close();
          onNavigate(); // closes the queue: the section may be behind it
        }}
      >
        {players?.length === 0 ? "Create a player…" : "Manage players…"}
      </Link>
    </>
  );
}
