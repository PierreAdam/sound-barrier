import { useEffect } from "react";

import { RemoteIcon } from "../components/Icons";
import { disableRemoteTarget, enableRemoteTarget, useRemoteTarget } from "./target";

const HINT =
  "Remote control: this tab's player can be driven from another tab, computer or phone " +
  "signed in to your account (menu under your name, “Remote control”). Off again when the page reloads.";

/** Queue panel: turns remote control of this tab on and off. */
export function RemoteToggle() {
  const status = useRemoteTarget();
  const on = status.kind === "on";

  // Already on in another tab for the same player: only one of them can be controlled.
  useEffect(() => {
    if (status.kind !== "conflict") return;
    const question = `Remote control is already on in another tab (${status.device}) for this player. Take over?`;
    if (window.confirm(question)) enableRemoteTarget({ takeOver: true });
    else disableRemoteTarget();
  }, [status]);

  const label =
    status.kind === "on"
      ? "Remote control: on"
      : status.kind === "connecting"
        ? "Remote control: connecting…"
        : "Remote control";
  return (
    <>
      <button
        className={`action-bar__item${on ? " action-bar__item--active" : ""}${
          status.kind === "connecting" ? " remote-toggle--connecting" : ""
        }`}
        type="button"
        aria-pressed={on || status.kind === "connecting"}
        title={HINT}
        onClick={() => (status.kind === "on" || status.kind === "connecting" ? disableRemoteTarget() : enableRemoteTarget())}
      >
        <RemoteIcon />
        {label}
      </button>
      {status.kind === "replaced" && (
        <span className="remote-toggle__note text-muted">Remote control moved to {status.device}</span>
      )}
    </>
  );
}
