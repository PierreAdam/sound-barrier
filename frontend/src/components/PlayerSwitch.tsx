import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type WebPlayer } from "../api/native";
import { useSession } from "../auth/AuthContext";
import { plural } from "../format";
import { setWebPlayerId, useWebPlayerId } from "../player/webPlayer";
import { Dropdown } from "./Dropdown";
import { CheckIcon, ChevronDownIcon, DevicesIcon } from "./Icons";

export const SWITCH_HINT =
  "Each player keeps its own queue. Switching pauses, keeps this queue in the player it belongs to, " +
  "and brings the other player's queue here (queues are not moved from one player to another).";

/** Queue panel: the player this browser plays, and a menu to switch to another of the user's. */
export function PlayerSwitch({ open }: { open: boolean }) {
  const { username } = useSession().user;
  const playerId = useWebPlayerId(username);
  const [players, setPlayers] = useState<WebPlayer[] | null>(null);

  // Asked each time the panel opens: players may have been created on another device.
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

  // Until the list comes: the current player, unnamed.
  const name = playerId ? (players?.find((player) => player.id === playerId)?.name ?? "…") : "Shared";
  const choices: { id: string | null; name: string; detail: string }[] = [
    { id: null, name: "Shared", detail: "every browser without a player" },
    ...(players ?? []).map((player) => ({
      id: player.id,
      name: player.name,
      detail: plural(player.songCount, "track"),
    })),
  ];

  return (
    <Dropdown
      className="player-switch-menu"
      fixed
      buttonClassName={`player-switch${playerId ? " player-switch--own" : ""}`}
      label={`Player: ${name}. Switch player`}
      title={SWITCH_HINT}
      button={
        <>
          <DevicesIcon />
          <span className="player-switch__label">Player</span>
          <span className="player-switch__name">{name}</span>
          <ChevronDownIcon />
        </>
      }
    >
      {(close) => (
        <>
          <p className="dropdown__header player-switch-menu__hint">{SWITCH_HINT}</p>
          {choices.map((choice) => {
            const current = choice.id === playerId;
            return (
              <button
                key={choice.id ?? "shared"}
                className={`dropdown__item player-switch-menu__item${current ? " dropdown__item--active" : ""}`}
                type="button"
                role="menuitemradio"
                aria-checked={current}
                onClick={() => {
                  setWebPlayerId(username, choice.id);
                  close();
                }}
              >
                <span className="player-switch-menu__check">{current && <CheckIcon />}</span>
                <span className="player-switch-menu__name">{choice.name}</span>
                <span className="player-switch-menu__detail">{choice.detail}</span>
              </button>
            );
          })}
          <Link
            className="dropdown__item dropdown__item--separated"
            role="menuitem"
            to="/account#players"
            onClick={close}
          >
            {players?.length === 0 ? "Create a player…" : "Manage players…"}
          </Link>
        </>
      )}
    </Dropdown>
  );
}
