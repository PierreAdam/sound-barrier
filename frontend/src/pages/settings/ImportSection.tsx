import { type FormEvent, useEffect, useState } from "react";

import { api, type ManageSettings } from "../../api/native";
import { FolderIcon } from "../../components/Icons";

/** Admins: import root folder and import options (used by the Library Management page). */
export function ImportSection() {
  const [settings, setSettings] = useState<ManageSettings | null>(null);
  const [root, setRoot] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    api
      .getManageSettings()
      .then((loaded) => {
        setSettings(loaded);
        setRoot(loaded.root ?? "");
      })
      .catch((e: unknown) => setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) }));
  }, []);

  if (!settings) {
    return (
      <section className="settings-section settings-section--wide">
        <h2 className="settings-section__title">Import</h2>
        {message ? <p className="text-error">{message.text}</p> : <p className="text-muted">Loading…</p>}
      </section>
    );
  }

  async function save(update: Partial<{ root: string | null; autoApplyStrong: boolean; transcodeLossless: boolean }>) {
    if (!settings) return;
    try {
      const saved = await api.setManageSettings({
        root: settings.root,
        autoApplyStrong: settings.autoApplyStrong,
        transcodeLossless: settings.transcodeLossless,
        ...update,
      });
      setSettings(saved);
      setRoot(saved.root ?? "");
      setMessage({ ok: true, text: "Import settings saved." });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void save({ root: root.trim() || null });
  }

  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">Import</h2>
      <form className="folder-form" onSubmit={onSubmit}>
        <label className="field">
          <span className="field__label">Import root folder</span>
          <div className="folder-form__row">
            <FolderIcon />
            <input
              className="field__input"
              placeholder="/downloads or W:\\downloads"
              spellCheck={false}
              value={root}
              onChange={(e) => setRoot(e.target.value)}
            />
            <button className="button button--primary" type="submit" disabled={root.trim() === (settings.root ?? "")}>
              Save
            </button>
          </div>
        </label>
        {settings.root && !settings.rootReachable && (
          <p className="text-error">This folder is not reachable from the server.</p>
        )}
        <p className="text-muted">
          Where new music is downloaded. The Library Management page shows what is inside it; only this folder and its
          sub-folders can be browsed and imported. Files are copied into the library: the originals are kept.
        </p>
      </form>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.transcodeLossless}
          disabled={!settings.ffmpegAvailable}
          onChange={(e) => void save({ transcodeLossless: e.target.checked })}
        />
        <span>
          Convert lossless files (FLAC, WAV, AIFF, APE, WavPack) to MP3 320 kbps while importing (with ffmpeg; tags
          and covers are kept)
        </span>
      </label>
      {!settings.ffmpegAvailable && <p className="text-error">ffmpeg is not installed on the server.</p>}

      <label className="checkbox">
        <input
          type="checkbox"
          checked={settings.autoApplyStrong}
          onChange={(e) => void save({ autoApplyStrong: e.target.checked })}
        />
        <span>Import confident matches without asking (only doubtful albums wait for review)</span>
      </label>
      {message && <p className={message.ok ? "text-success" : "text-error"}>{message.text}</p>}
    </section>
  );
}
