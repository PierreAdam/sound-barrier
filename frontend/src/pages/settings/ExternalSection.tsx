import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import { api, type ExternalSettings, type ExternalSettingsUpdate } from "../../api/native";

const LASTFM_CREATE_URL = "https://www.last.fm/api/account/create";
const FANART_KEY_URL = "https://fanart.tv/get-an-api-key/";

/** Admins: artist information (Last.fm), artist pictures and album covers sources. */
export function ExternalSection() {
  const [settings, setSettings] = useState<ExternalSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    api
      .getExternalSettings()
      .then(setSettings)
      .catch((e: unknown) => setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) }));
  }, []);

  async function save(update: ExternalSettingsUpdate, done: string): Promise<boolean> {
    if (!settings) return false;
    setBusy(true);
    try {
      setSettings(await api.setExternalSettings({ pictureSource: settings.pictureSource, ...update }));
      setMessage({ ok: true, text: done });
      return true;
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  if (!settings) {
    return (
      <section className="settings-section settings-section--wide">
        <h2 className="settings-section__title">External services</h2>
        {message ? <p className="text-error">{message.text}</p> : <p className="text-muted">Loading…</p>}
      </section>
    );
  }

  const keySet: Record<string, boolean> = { fanart: settings.fanartKeySet };
  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">External services</h2>
      <p className="text-muted">
        Artist pages show a biography, similar artists and top songs from Last.fm, and a picture. Only artist names
        and MusicBrainz ids are sent, by the server; results are kept for 30 days.
      </p>

      <KeyField
        label="Last.fm API key"
        set={settings.lastfmKeySet}
        busy={busy}
        onSave={(key) => save({ lastfmKey: key }, key ? "Last.fm API key checked and saved." : "Last.fm API key removed.")}
        help={
          <>
            Free, for non-commercial use:{" "}
            <a className="link" href={LASTFM_CREATE_URL} target="_blank" rel="noreferrer">
              create an API account on Last.fm
            </a>{" "}
            and paste its API key. Biographies, similar artists and top songs.
          </>
        }
      />

      <KeyField
        label="fanart.tv API key"
        set={settings.fanartKeySet}
        busy={busy}
        onSave={(key) => save({ fanartKey: key }, key ? "fanart.tv API key checked and saved." : "fanart.tv API key removed.")}
        help={
          <>
            <a className="link" href={FANART_KEY_URL} target="_blank" rel="noreferrer">
              Get a personal API key
            </a>{" "}
            (free). Artist pictures and album covers, for artists and albums with MusicBrainz ids in their tags.
          </>
        }
      />

      <label className="field field--inline">
        <span className="field__label">Artist pictures</span>
        <select
          className="field__input"
          value={settings.pictureSource}
          disabled={busy}
          onChange={(e) => void save({ pictureSource: e.target.value }, "Picture source saved.")}
        >
          {settings.pictureSources.map((source) => {
            const missing = source.needsKey && !keySet[source.needsKey];
            return (
              <option key={source.id} value={source.id} disabled={Boolean(missing)}>
                {source.label}
                {missing ? " (needs its API key)" : ""}
              </option>
            );
          })}
        </select>
      </label>
      <p className="text-muted">Album covers are searched on every source that is set up (the pen on an album cover).</p>
      {message && <p className={message.ok ? "text-success" : "text-error"}>{message.text}</p>}
    </section>
  );
}

/** An API key: stored encrypted by the server and never shown again; replace or remove. */
function KeyField({
  label,
  set,
  busy,
  help,
  onSave,
}: {
  label: string;
  set: boolean;
  busy: boolean;
  help: ReactNode;
  onSave(key: string): Promise<boolean>;
}) {
  const [key, setKey] = useState("");

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (key.trim()) void onSave(key.trim()).then((ok) => ok && setKey(""));
  }

  return (
    <form className="folder-form" onSubmit={onSubmit}>
      <label className="field">
        <span className="field__label">
          {label} {set ? <span className="badge">configured</span> : <span className="text-muted">(not set)</span>}
        </span>
        <div className="folder-form__row">
          <input
            className="field__input"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder={set ? "Enter a new key to replace it" : "Paste the key"}
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
          <button className="button button--primary" type="submit" disabled={busy || !key.trim()}>
            Save
          </button>
          {set && (
            <button className="button" type="button" disabled={busy} onClick={() => void onSave("")}>
              Remove
            </button>
          )}
        </div>
      </label>
      <p className="text-muted">
        {help} It is checked, stored encrypted and never shown again.
      </p>
    </form>
  );
}
