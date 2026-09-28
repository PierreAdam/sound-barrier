import { usePreferences } from "../../preferences/PreferencesContext";
import { ACCENTS, type Appearance, type ThemeMode } from "../../theme/appearance";

const MODES: { id: ThemeMode; label: string }[] = [
  { id: "dark", label: "Dark" },
  { id: "light", label: "Light" },
  { id: "system", label: "System" },
];

/** Theme and accent color (saved with the account: they follow the user). */
export function AppearanceSection() {
  const { preferences, update, saveError } = usePreferences();
  if (!preferences) {
    return (
      <section className="settings-section">
        <h2 className="settings-section__title">Appearance</h2>
        <p className="text-muted">Loading…</p>
      </section>
    );
  }
  const theme = preferences.theme;
  const change = (next: Partial<Appearance>) =>
    update((current) => ({ ...current, theme: { ...current.theme, ...next } }));

  return (
    <section className="settings-section">
      <h2 className="settings-section__title">Appearance</h2>
      <div className="field">
        <span className="field__label" id="theme-mode-label">
          Theme
        </span>
        <div className="segmented" role="radiogroup" aria-labelledby="theme-mode-label">
          {MODES.map((mode) => (
            <button
              key={mode.id}
              type="button"
              role="radio"
              aria-checked={theme.mode === mode.id}
              className={`segmented__option${theme.mode === mode.id ? " segmented__option--active" : ""}`}
              onClick={() => change({ mode: mode.id })}
            >
              {mode.label}
            </button>
          ))}
        </div>
        {theme.mode === "system" && <span className="text-muted">Follows the light / dark setting of your device.</span>}
      </div>
      <div className="field">
        <span className="field__label" id="theme-accent-label">
          Accent color
        </span>
        <div className="swatches" role="radiogroup" aria-labelledby="theme-accent-label">
          {ACCENTS.map((accent) => (
            <button
              key={accent.id}
              type="button"
              role="radio"
              aria-checked={theme.accent === accent.id}
              aria-label={accent.label}
              title={accent.label}
              data-accent={accent.id}
              className={`swatch${theme.accent === accent.id ? " swatch--active" : ""}`}
              onClick={() => change({ accent: accent.id })}
            />
          ))}
        </div>
      </div>
      {saveError ? (
        <p className="text-error">Not saved: {saveError}</p>
      ) : (
        <p className="text-muted">Saved with your account: the same on all your devices.</p>
      )}
    </section>
  );
}
