import { MAX_CROSSFADE_SECONDS } from "../../player/engine";
import { usePlayer } from "../../player/PlayerContext";

/** Player preferences: crossfade is saved with the account (see PlayerContext). */
export function PlayerSection() {
  const { state, engine } = usePlayer();
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
    </section>
  );
}
