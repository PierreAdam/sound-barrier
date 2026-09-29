import { type FormEvent, useEffect, useState } from "react";

import { api, type SpokenFolder, type SpokenKind } from "../../api/native";
import { useSections } from "../../api/useSections";

const LABELS: Record<SpokenKind, { title: string; example: string }> = {
  podcasts: { title: "Podcasts", example: "/podcasts" },
  audiobooks: { title: "Audiobooks", example: "/audiobooks" },
};

/**
 * Admins: podcasts and audiobooks, each with its own folder (never inside the music
 * folder) and an on / off switch (its menu entry, import choice and Subsonic channels).
 */
export function SpokenSection() {
  const [folders, setFolders] = useState<Record<SpokenKind, SpokenFolder> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getSpokenFolders()
      .then(setFolders)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">Podcasts and audiobooks</h2>
      <p className="text-muted">
        Kept apart from the music, each in its own folder. Subsonic apps get both as podcasts. Import them with
        Library Management → Import ("Import as"), or copy them into their folder.
      </p>
      {error && <p className="text-error">{error}</p>}
      {folders &&
        (["podcasts", "audiobooks"] as const).map((kind) => (
          <SpokenFolderForm key={kind} kind={kind} current={folders[kind]} onSaved={setFolders} />
        ))}
    </section>
  );
}

function SpokenFolderForm({
  kind,
  current,
  onSaved,
}: {
  kind: SpokenKind;
  current: SpokenFolder;
  onSaved(folders: Record<SpokenKind, SpokenFolder>): void;
}) {
  const { refresh } = useSections();
  const [path, setPath] = useState(current.folder?.path ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const { title, example } = LABELS[kind];

  async function save(enabled: boolean, newPath?: string) {
    setBusy(true);
    try {
      const saved = await api.setSpokenFolder(kind, enabled, newPath);
      onSaved(saved);
      refresh(); // the menu entry
      setMessage({ ok: true, text: "Saved." });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void save(current.enabled, path.trim());
  }

  return (
    <form className="folder-form spoken-settings" onSubmit={onSubmit}>
      <label className="checkbox spoken-settings__switch">
        <input
          type="checkbox"
          checked={current.enabled}
          disabled={busy}
          onChange={(e) => void save(e.target.checked)}
        />
        <strong>{title}</strong>
        <span className="text-muted">{current.enabled ? "on" : "off"}</span>
      </label>
      <label className="field">
        <span className="field__label">
          {title} folder{" "}
          {current.folder && !current.folder.reachable && <span className="text-error">(not reachable)</span>}
        </span>
        <div className="folder-form__row">
          <input
            className="field__input"
            value={path}
            placeholder={`Optional, e.g. ${example}`}
            spellCheck={false}
            onChange={(e) => setPath(e.target.value)}
          />
          <button className="button" type="submit" disabled={busy || path.trim() === (current.folder?.path ?? "")}>
            Save
          </button>
        </div>
      </label>
      {current.enabled && !current.folder && (
        <p className="text-warning">On, but without a folder: the section stays hidden until you set one.</p>
      )}
      {message && <p className={message.ok ? "text-success" : "text-error"}>{message.text}</p>}
    </form>
  );
}
