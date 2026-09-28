import { type DragEvent, type KeyboardEvent, useEffect, useState } from "react";

import { openAlbumLink } from "../../api/albumLinks";
import { api, type PluginField, type PluginInfo, type PluginSettings } from "../../api/native";

type Row = Record<string, unknown>;
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * Admins: "Album search", the plugins' settings, each with the form it describes (users
 * never see the word "plugin": it is an internal notion).
 */
export function PluginsSection() {
  const [plugins, setPlugins] = useState<PluginInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getPlugins()
      .then(setPlugins)
      .catch((e: unknown) => setError(errorText(e)));
  }, []);

  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">Album search</h2>
      {error && <p className="text-error">{error}</p>}
      {!plugins && !error && <p className="text-muted">Loading…</p>}
      {plugins?.map((plugin) => <PluginPanel key={plugin.id} initial={plugin} />)}
    </section>
  );
}

function PluginPanel({ initial }: { initial: PluginInfo }) {
  const [plugin, setPlugin] = useState(initial);
  const [enabled, setEnabled] = useState(initial.enabled);
  const [settings, setSettings] = useState<PluginSettings>(initial.settings);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [version, setVersion] = useState(0); // reloads the icons after a save
  const hasIcons = plugin.fields.some((f) => f.iconAsset);

  async function save(refresh = false) {
    setBusy(true);
    try {
      const saved = await api.savePlugin(plugin.id, enabled, settings, refresh);
      setPlugin(saved.plugin);
      setSettings(saved.plugin.settings);
      setWarnings(saved.warnings);
      setVersion((v) => v + 1);
      setMessage({ ok: true, text: "Saved." });
    } catch (e) {
      setMessage({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  async function tryRow(field: PluginField, index: number) {
    try {
      const [link] = await api.tryPlugin(plugin.id, settings, field.key, index);
      if (link) openAlbumLink(link);
      setMessage(null);
    } catch (e) {
      setMessage({ ok: false, text: errorText(e) });
    }
  }

  return (
    <div className="plugin">
      <div className="plugin__header">
        <label className="checkbox plugin__toggle">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <span className="plugin__name">{plugin.name}</span>
        </label>
      </div>
      <p className="text-muted">{plugin.description}</p>
      {plugin.fields.map((field) => (
        <FieldEditor
          key={field.key}
          field={field}
          value={settings[field.key]}
          onChange={(value) => setSettings((current) => ({ ...current, [field.key]: value }))}
          iconUrl={(asset) => `${api.pluginAssetUrl(plugin.id, asset)}?v=${version}`}
          onTry={plugin.capabilities.includes("links") ? (index) => void tryRow(field, index) : undefined}
        />
      ))}
      <div className="settings-section__actions">
        <button className="button button--primary" type="button" disabled={busy} onClick={() => void save()}>
          {busy ? "Saving…" : "Save"}
        </button>
        {hasIcons && (
          <button className="button button--ghost" type="button" disabled={busy} onClick={() => void save(true)}>
            Save and fetch icons again
          </button>
        )}
      </div>
      {message && <p className={message.ok ? "text-success" : "text-error"}>{message.text}</p>}
      {warnings.map((warning) => (
        <p key={warning} className="text-warning">
          {warning}
        </p>
      ))}
    </div>
  );
}

function visible(field: PluginField, values: Row): boolean {
  return !field.visibleWhen || values[field.visibleWhen[0]] === field.visibleWhen[1];
}

/** One field of a plugin's form (a list is a set of rows of sub-fields). */
function FieldEditor({
  field,
  value,
  onChange,
  iconUrl,
  onTry,
}: {
  field: PluginField;
  value: unknown;
  onChange(value: unknown): void;
  iconUrl(asset: string): string;
  onTry?: (index: number) => void;
}) {
  if (field.type === "list") {
    return (
      <ListEditor
        field={field}
        rows={Array.isArray(value) ? (value as Row[]) : []}
        onChange={onChange}
        iconUrl={iconUrl}
        onTry={field.canTry ? onTry : undefined}
      />
    );
  }
  if (field.type === "boolean") {
    return (
      <label className="checkbox">
        <input type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
        {field.label}
      </label>
    );
  }
  return (
    <label className="field">
      <span className="field__label">{field.label}</span>
      {field.type === "select" ? (
        <select className="field__input" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {field.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : field.type === "textarea" ? (
        <textarea
          className="field__input plugin__textarea"
          value={String(value ?? "")}
          placeholder={field.placeholder ?? undefined}
          spellCheck={false}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          className="field__input"
          value={String(value ?? "")}
          placeholder={field.placeholder ?? undefined}
          spellCheck={false}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {field.help && <span className="field__help text-muted">{field.help}</span>}
    </label>
  );
}

function moved<T>(items: T[], from: number, to: number): T[] {
  const next = [...items];
  next.splice(to, 0, ...next.splice(from, 1));
  return next;
}

function newRow(field: PluginField): Row {
  return Object.fromEntries(
    field.fields.map((sub) => [sub.key, sub.type === "boolean" ? true : sub.type === "select" ? sub.options[0] : ""]),
  );
}

/** Rows that can be added, removed, opened and reordered by drag and drop. */
function ListEditor({
  field,
  rows,
  onChange,
  iconUrl,
  onTry,
}: {
  field: PluginField;
  rows: Row[];
  onChange(rows: Row[]): void;
  iconUrl(asset: string): string;
  onTry?: (index: number) => void;
}) {
  const [open, setOpen] = useState<Set<number>>(() => new Set());
  const [dragged, setDragged] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);

  function move(from: number, to: number) {
    if (from === to || to < 0 || to >= rows.length) return;
    onChange(moved(rows, from, to));
    // The open rows follow their row.
    const order = moved(
      rows.map((_, index) => index),
      from,
      to,
    );
    setOpen(new Set(order.flatMap((oldIndex, newIndex) => (open.has(oldIndex) ? [newIndex] : []))));
  }
  function update(index: number, key: string, value: unknown) {
    onChange(rows.map((row, i) => (i === index ? { ...row, [key]: value } : row)));
  }
  function remove(index: number) {
    onChange(rows.filter((_, i) => i !== index));
    setOpen(new Set([...open].filter((i) => i !== index).map((i) => (i > index ? i - 1 : i))));
  }
  function add() {
    onChange([...rows, newRow(field)]);
    setOpen(new Set([...open, rows.length]));
  }
  function toggle(index: number) {
    const next = new Set(open);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setOpen(next);
  }

  const drop = (index: number) => (event: DragEvent) => {
    event.preventDefault();
    if (dragged !== null) move(dragged, index);
    setDragged(null);
    setOver(null);
  };
  const keyMove = (index: number) => (event: KeyboardEvent) => {
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      move(index, index + (event.key === "ArrowUp" ? -1 : 1));
    }
  };

  return (
    <div className="field">
      <span className="field__label">{field.label}</span>
      {field.help && <span className="field__help text-muted">{field.help}</span>}
      <ul className="plugin-list">
        {rows.map((row, index) => {
          const id = field.idKey ? String(row[field.idKey] ?? "") : "";
          const label = field.itemLabel ? String(row[field.itemLabel] ?? "") : "";
          const disabled = row.enabled === false;
          const classes = [
            "plugin-list__row",
            dragged === index && "plugin-list__row--dragged",
            over === index && dragged !== index && "plugin-list__row--over",
          ].filter(Boolean);
          return (
            <li
              key={index}
              className={classes.join(" ")}
              onDragOver={(event) => {
                event.preventDefault();
                setOver(index);
              }}
              onDragLeave={() => setOver((current) => (current === index ? null : current))}
              onDrop={drop(index)}
            >
              <div
                className="plugin-list__header"
                draggable
                onDragStart={(event) => {
                  event.dataTransfer.effectAllowed = "move";
                  setDragged(index);
                }}
                onDragEnd={() => {
                  setDragged(null);
                  setOver(null);
                }}
              >
                <button
                  className="plugin-list__handle"
                  type="button"
                  aria-label={`Move ${label || "this row"} (arrow keys)`}
                  title="Drag to reorder"
                  onKeyDown={keyMove(index)}
                >
                  ⠿
                </button>
                {field.iconAsset && <RowIcon src={id ? iconUrl(field.iconAsset.replace("{id}", id)) : null} />}
                <button className="plugin-list__title" type="button" onClick={() => toggle(index)} aria-expanded={open.has(index)}>
                  {label || "New"}
                  {disabled && <span className="text-muted"> (off)</span>}
                </button>
                {onTry && (
                  <button className="button button--ghost" type="button" onClick={() => onTry(index)} title="Search a sample album">
                    Try
                  </button>
                )}
                <button className="button button--ghost button--danger" type="button" onClick={() => remove(index)}>
                  Remove
                </button>
              </div>
              {open.has(index) && (
                <div className="plugin-list__body">
                  {field.fields
                    .filter((sub) => visible(sub, row))
                    .map((sub) => (
                      <FieldEditor
                        key={sub.key}
                        field={sub}
                        value={row[sub.key]}
                        onChange={(value) => update(index, sub.key, value)}
                        iconUrl={iconUrl}
                      />
                    ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <div>
        <button className="button" type="button" onClick={add}>
          Add
        </button>
      </div>
    </div>
  );
}

function RowIcon({ src }: { src: string | null }) {
  const [failed, setFailed] = useState<string | null>(null);
  if (!src || failed === src) return <span className="plugin-list__icon plugin-list__icon--none" aria-hidden />;
  return <img className="plugin-list__icon" src={src} alt="" onError={() => setFailed(src)} />;
}
