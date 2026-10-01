import { useSyncExternalStore } from "react";

import { MAX_CROSSFADE_SECONDS } from "../../player/engine";
import { useLocalPlayer } from "../../player/PlayerContext";
import { LOW_POWER_FPS, setLowPower, useLowPower } from "../../preferences/lowPower";

/** Player preferences: crossfade is saved with the account (see PlayerContext), lighter
 * animations in this browser (lowPower.ts). */
export function PlayerSection() {
  // A setting of this browser's own player (and saved for the user), even in remote mode.
  const engine = useLocalPlayer();
  const state = useSyncExternalStore(engine.subscribe, engine.getSnapshot);
  const lowPower = useLowPower();
  return (
    <section className="settings-section">
      <h2 className="settings-section__title">Player</h2>
      <label className="checkbox">
        <input type="checkbox" checked={state.crossfade} onChange={() => engine.toggleCrossfade()} />
        <span>Crossfade: start the next song before the current one ends</span>
      </label>
      <label className="field field--inline">
        <span className="field__label">Crossfade duration</span>
        <input
          className="slider settings-section__slider"
          type="range"
          min={1}
          max={MAX_CROSSFADE_SECONDS}
          step={1}
          value={state.crossfadeSeconds}
          onChange={(e) => engine.setCrossfadeSeconds(Number(e.target.value))}
        />
        <span className="settings-section__value">{state.crossfadeSeconds} s</span>
      </label>
      <p className="text-muted">
        Crossfade is saved with your account. Volume, shuffle and repeat are kept in each browser.
      </p>
      <label className="checkbox">
        <input type="checkbox" checked={lowPower} onChange={() => setLowPower(!lowPower)} />
        <span>
          Lighter animations, for a less powerful computer: the visualizers and the lyrics draw {LOW_POWER_FPS} frames a
          second instead of the screen&apos;s rate
        </span>
      </label>
      <p className="text-muted">Kept in this browser: the same account may be used on a desktop and a small laptop.</p>
    </section>
  );
}
