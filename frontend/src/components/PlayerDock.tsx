import { useEffect, useRef, useState } from "react";

import { PlayerBar } from "./PlayerBar";
import { QueuePanel } from "./QueuePanel";

/** Delays before hovering the player opens / leaving closes the queue (avoids flicker). */
const OPEN_DELAY_MS = 300;
const CLOSE_DELAY_MS = 350;

function canHover(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(hover: hover)").matches;
}

/**
 * Player bar + queue panel. Like Subsonic, hovering the player opens the queue; the
 * queue button pins it open (and is the only way on touch screens).
 */
export function PlayerDock() {
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const open = pinned || hovered;

  function hoverAfter(value: boolean, delay: number) {
    if (!canHover()) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setHovered(value), delay);
  }

  function close() {
    clearTimeout(timer.current);
    setPinned(false);
    setHovered(false);
  }

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <div
      className="player-dock"
      onMouseEnter={() => hoverAfter(true, OPEN_DELAY_MS)}
      onMouseLeave={() => hoverAfter(false, CLOSE_DELAY_MS)}
    >
      {/* The queue slides up out of the player bar (clipped by its slot above it). */}
      <div className="queue-slot">
        <QueuePanel open={open} onClose={close} />
      </div>
      <PlayerBar
        queueOpen={open}
        onToggleQueue={() => {
          if (open) close();
          else setPinned(true);
        }}
      />
    </div>
  );
}
