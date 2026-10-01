import { useState } from "react";

import { useSession } from "../../auth/AuthContext";
import { InfoTip } from "../../components/InfoTip";
import { useLocalPlayer } from "../../player/PlayerContext";
import type { RemoteCommand } from "../../remote/protocol";
import { controlTarget, playHere, setModeNotice, usePlayerMode } from "../../remote/mode";
import { canCastScreen, castScreen, openScreenWindow, type ScreenChannel } from "./channel";
import { SCREEN_TARGET, screenLink } from "./screenLink";

const NAME = "TV";

/**
 * "Player" menu, this browser: its player to a TV, without the server player. A TV page
 * (tv.html) plays this queue, cast from this computer (Chrome's Presentation API) or in a
 * window; this tab drives it in remote mode, and takes the queue back on "Play here".
 */
export function ScreenActions({ close }: { close(): void }) {
  const { client } = useSession();
  const engine = useLocalPlayer();
  const [message, setMessage] = useState<string | null>(null);
  const cast = canCastScreen();

  function begin(channel: ScreenChannel | null) {
    if (!channel) return; // no device chosen, or no window
    // This queue goes on there, where it is (playing if it was).
    const queue = engine.exportQueue();
    const playing = engine.getSnapshot().playing;
    const first: RemoteCommand[] = queue.tracks.length
      ? [{ name: "playQueue", tracks: queue.tracks, index: Math.max(queue.index, 0), startAt: queue.position }]
      : [];
    if (first.length && !playing) first.push({ name: "pause" });
    screenLink.start(channel, client, NAME, first, (blocked) =>
      setModeNotice(blocked ? "The TV page waits for a click to start the sound (the browser asks for one)" : null),
    );
    // Still controllable if it was: the other devices then control the TV through this tab.
    controlTarget(SCREEN_TARGET, NAME, "screen");
    close();
  }

  async function castIt() {
    setMessage(null);
    try {
      begin(await castScreen());
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }

  function openWindow() {
    setMessage(null);
    const channel = openScreenWindow();
    if (!channel) setMessage("The browser blocked the window: allow pop-ups for this site");
    begin(channel);
  }

  const mode = usePlayerMode();
  const onScreen = mode.kind === "remote" && mode.targetKind === "screen";

  return (
    <>
      <div className="playback-menu__option">
        {/* On the TV already: only the way back (casting again would start over). */}
        <div className="remote-menu__actions screen-actions">
          {onScreen ? (
            <button className="button button--ghost" type="button" onClick={() => playHere()}>
              Back here
            </button>
          ) : (
            <>
              {cast && (
                <button className="button button--ghost" type="button" onClick={() => void castIt()}>
                  Cast this player…
                </button>
              )}
              <button className="button button--ghost" type="button" onClick={openWindow}>
                TV window
              </button>
            </>
          )}
        </div>
        <InfoTip label="About casting this player">
          <p>
            <strong>Cast this player</strong>: plays this browser&apos;s queue on a TV, with Now playing and synced
            lyrics, without the server player.
          </p>
        </InfoTip>
      </div>
      {message && <p className="dropdown__header remote-menu__note">{message}</p>}
    </>
  );
}
