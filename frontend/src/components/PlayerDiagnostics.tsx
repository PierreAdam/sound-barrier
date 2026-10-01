import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";

import { audioTrace, clearAudioTrace, subscribeAudioTrace } from "../player/audioTrace";
import { PLAYER_DIAGNOSTICS_EVENT, playerDiagnosticsOpen, setPlayerDiagnosticsOpen } from "../pwa/diagnostics";

/** Followed when this close to the bottom: a log being read further up stays where it is. */
const FOLLOW_PX = 24;

/**
 * About → "Player diagnostics": what the player's audio did lately (audioTrace.ts), as a
 * log, newest last. Above the player bar, so the display diagnostics can be open too.
 */
export function PlayerDiagnostics() {
  const [open, setOpen] = useState(playerDiagnosticsOpen);
  const [folded, setFolded] = useState(false);
  const [copied, setCopied] = useState(false);
  const lines = useSyncExternalStore(subscribeAudioTrace, audioTrace);
  const log = useRef<HTMLOListElement>(null);
  const following = useRef(true);

  useEffect(() => {
    const onToggle = () => setOpen(playerDiagnosticsOpen());
    window.addEventListener(PLAYER_DIAGNOSTICS_EVENT, onToggle);
    return () => window.removeEventListener(PLAYER_DIAGNOSTICS_EVENT, onToggle);
  }, []);

  // New lines: the log scrolls to them, unless it is read further up.
  useLayoutEffect(() => {
    const element = log.current;
    if (element && following.current) element.scrollTop = element.scrollHeight;
  }, [lines, open, folded]);

  useEffect(() => setCopied(false), [lines]);

  if (!open) return null;

  async function copy() {
    // The browser first: what the log means depends on it.
    const text = [navigator.userAgent, ...lines.map((line) => `${line.time} ${line.text}`)].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section
      className={`diagnostics diagnostics--player${folded ? " diagnostics--folded" : ""}`}
      aria-label="Player diagnostics"
    >
      <div className="diagnostics__bar">
        <strong>Player diagnostics</strong>
        <button className="diagnostics__button" type="button" onClick={() => setFolded(!folded)}>
          {folded ? "Show" : "Fold"}
        </button>
        <button className="diagnostics__button" type="button" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy"}
        </button>
        <button className="diagnostics__button" type="button" onClick={clearAudioTrace}>
          Clear
        </button>
        <button className="diagnostics__button" type="button" onClick={() => setPlayerDiagnosticsOpen(false)}>
          Close
        </button>
      </div>
      {!folded && (
        <ol
          ref={log}
          className="diagnostics__log"
          onScroll={(e) => {
            const element = e.currentTarget;
            following.current = element.scrollHeight - element.scrollTop - element.clientHeight < FOLLOW_PX;
          }}
        >
          {lines.length === 0 && <li className="diagnostics__empty">Nothing yet: play something.</li>}
          {lines.map((line) => (
            <li key={line.id}>
              <time>{line.time}</time> {line.text}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
