import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import { api, type ExternalSettings, type ExternalSettingsUpdate } from "../../api/native";
import { SecretInput } from "../../components/SecretInput";

const LASTFM_CREATE_URL = "https://www.last.fm/api/account/create";
const FANART_KEY_URL = "https://fanart.tv/get-an-api-key/";

/** Admins: artist information (Last.fm), artist pictures, album covers sources and discographies (MusicBrainz). */
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
      <p className="text-muted">
        Album covers are searched on every source that is set up (the pen on an album cover); the Cover Art Archive
        needs a MusicBrainz release group id in the tags.
      </p>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.musicbrainz}
          disabled={busy}
          onChange={(e) =>
            void save(
              { musicbrainz: e.target.checked },
              e.target.checked ? "MusicBrainz lookups turned on." : "MusicBrainz lookups turned off.",
            )
          }
        />
        Use MusicBrainz (no key needed): artist discographies ("Missing albums" on artist pages, kept a day) and
        audiobook editions in the import review (chapter titles)
      </label>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.lrclib}
          disabled={busy}
          onChange={(e) =>
            void save(
              { lrclib: e.target.checked },
              e.target.checked ? "LRCLIB lyrics turned on." : "LRCLIB lyrics turned off.",
            )
          }
        />
        Look up song lyrics on LRCLIB when the files have none (synced lyrics, no key needed; kept on the server)
      </label>

      <h3 className="settings-section__subtitle">Audiobook and podcast imports</h3>
      <p className="text-muted">Candidates shown in the review, to fill in the title, author, narrator, series and cover.</p>
      <div className="external-lookup">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={settings.audible}
            disabled={busy}
            onChange={(e) =>
              void save({ audible: e.target.checked }, e.target.checked ? "Audible lookups turned on." : "Audible lookups turned off.")
            }
          />
          Audible (audiobooks: narrator, series, cover; unofficial catalog API, no key needed)
        </label>
        <select
          className="field__input external-lookup__region"
          aria-label="Audible store"
          value={settings.audibleRegion}
          disabled={busy || !settings.audible}
          onChange={(e) => void save({ audibleRegion: e.target.value }, `Audible store: audible.${e.target.value}.`)}
        >
          {settings.audibleRegions.map((region) => (
            <option key={region} value={region}>
              audible.{region}
            </option>
          ))}
        </select>
      </div>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.openLibrary}
          disabled={busy}
          onChange={(e) =>
            void save(
              { openLibrary: e.target.checked },
              e.target.checked ? "Open Library lookups turned on." : "Open Library lookups turned off.",
            )
          }
        />
        Open Library (audiobooks: title, author, year, cover; no key needed)
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.itunes}
          disabled={busy}
          onChange={(e) =>
            void save({ itunes: e.target.checked }, e.target.checked ? "iTunes lookups turned on." : "iTunes lookups turned off.")
          }
        />
        iTunes (podcasts: show name, author, artwork; no key needed)
      </label>
      <CastReceiverField
        appId={settings.castReceiverAppId}
        busy={busy}
        onSave={(appId) =>
          save(
            { castReceiverAppId: appId },
            appId ? "Cast receiver saved: casting shows Now playing on the TV." : "Cast receiver removed.",
          )
        }
      />
      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.dashcast}
          disabled={busy}
          onChange={(e) =>
            void save(
              { dashcast: e.target.checked },
              e.target.checked ? "DashCast turned on." : "DashCast turned off: without a receiver of your own, sound only.",
            )
          }
        />
        DashCast (without a receiver of your own: the Now playing screen on the TV through this published receiver, a
        third party&apos;s, which is given the screen&apos;s address with the stream&apos;s key; “Cast from this computer”
        stays private)
      </label>
      {message &&<p className={message.ok ? "text-success" : "text-error"}>{message.text}</p>}
    </section>
  );
}

/**
 * The Google Cast app of Sound-Barrier's receiver: the server player's Now playing screen
 * on the TV. Registered by whoever hosts the page (receiver.html, served by this server).
 */
function CastReceiverField({
  appId,
  busy,
  onSave,
}: {
  appId: string | null;
  busy: boolean;
  onSave(appId: string): Promise<boolean>;
}) {
  const [value, setValue] = useState(appId ?? "");
  useEffect(() => setValue(appId ?? ""), [appId]);
  const receiverUrl = `${window.location.origin}/cast/receiver.html`;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void onSave(value.trim());
  }

  return (
    <form className="folder-form" onSubmit={onSubmit}>
      <label className="field">
        <span className="field__label">
          Cast receiver (Now playing on the TV){" "}
          {appId ? <span className="badge">configured</span> : <span className="text-muted">(sound only)</span>}
        </span>
        <div className="folder-form__row">
          <input
            className="field__input"
            placeholder="Application id, e.g. 1A2B3C4D"
            value={value}
            maxLength={8}
            onChange={(e) => setValue(e.target.value)}
          />
          <button className="button button--primary" type="submit" disabled={busy || value.trim() === (appId ?? "")}>
            Save
          </button>
          {appId && (
            <button className="button" type="button" disabled={busy} onClick={() => void onSave("")}>
              Remove
            </button>
          )}
        </div>
      </label>
      <p className="text-muted">
        Casting the server player to a Chromecast then shows its cover, progress and lyrics on the TV. Register a
        “Custom Receiver” in the Google Cast SDK Developer Console with the URL <code>{receiverUrl}</code> (or where you
        host a copy of it), then its id here. Until the app is published, only the Chromecasts registered there for
        testing can show it; the others cast the sound only (“▾” next to Cast).
      </p>
    </form>
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
          <SecretInput
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
