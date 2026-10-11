import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { CopyIcon, ExternalIcon, RemoveIcon } from "../components/Icons";
import {
  DEFAULT_RADIO_OPTIONS,
  MAX_DELAY,
  MAX_WIDTH,
  RADIO_RATIOS,
  type RadioOptions,
  radioTextUrl,
  radioUrl,
} from "../radio/options";
import { ACCENTS } from "../theme/appearance";
import {
  BIT_RATES,
  DEFAULT_BIT_RATE,
  DEFAULT_STREAM_OPTIONS,
  MAX_BURST,
  type StreamOptions,
  streamUrlWith,
} from "./streamUrl";

const OPTIONS_KEY = "sound-barrier.stream-url";
const RADIO_OPTIONS_KEY = "sound-barrier.radio-url";
const MAX_SHOWN_UPCOMING = 10; // in the dialog (the page takes up to 20)
const SHAPE_LABELS: Record<RadioOptions["ratio"], string> = {
  auto: "Automatic",
  "1:1": "Square (1:1)",
  "4:3": "4:3",
  "16:9": "Wide (16:9)",
  "3:4": "Portrait (3:4)",
};
const WIDTHS = [0, 320, 480, 512, 640, 800, 1024, 1280, 1920]; // px; 0: fills the window

function stored<T extends object>(key: string, defaults: T, valid: (options: T) => boolean): T {
  try {
    const options = { ...defaults, ...(JSON.parse(localStorage.getItem(key) ?? "null") as Partial<T> | null) };
    return valid(options) ? options : defaults;
  } catch {
    return defaults; // nothing kept, or private browsing
  }
}

function keep(key: string, options: object): void {
  try {
    localStorage.setItem(key, JSON.stringify(options));
  } catch {
    // private browsing: only for this page
  }
}

const validStream = (o: StreamOptions) =>
  (BIT_RATES as readonly number[]).includes(o.bitRate) &&
  typeof o.burst === "number" &&
  o.burst >= 0 &&
  o.burst <= MAX_BURST &&
  typeof o.titles === "boolean";

const validRadio = (o: RadioOptions) =>
  (o.layout === "card" || o.layout === "banner") &&
  ["auto", "dark", "light"].includes(o.theme) &&
  ACCENTS.some((a) => a.id === o.accent) &&
  typeof o.upcoming === "number" &&
  typeof o.delay === "number" &&
  o.delay >= 0 &&
  o.delay <= MAX_DELAY &&
  typeof o.cover === "boolean" &&
  typeof o.listeners === "boolean" &&
  RADIO_RATIOS.includes(o.ratio) &&
  typeof o.width === "number" &&
  o.width >= 0 &&
  o.width <= MAX_WIDTH;

/** A URL to copy (and to open, for a page). */
function UrlRow({ label, url, open }: { label: string; url: string; open?: boolean }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => setCopied(false), [url]);
  return (
    <div className="stream-url-dialog__url">
      <input className="field__input" type="text" readOnly aria-label={label} value={url} onFocus={(e) => e.target.select()} />
      <button
        className="button button--ghost"
        type="button"
        onClick={() => void navigator.clipboard.writeText(url).then(() => setCopied(true))}
      >
        <CopyIcon /> {copied ? "Copied" : "Copy"}
      </button>
      {open && (
        <a className="button button--ghost" href={url} target="_blank" rel="noreferrer" aria-label={`Open the ${label}`}>
          <ExternalIcon />
        </a>
      )}
    </div>
  );
}

/**
 * The server player's stream URL, with its options (quality, buffer, titles), for VLC or an
 * internet radio app; and its "now playing" page (/radio/<key>), for a screen or a web
 * page. The options are kept in this browser.
 */
type Panel = "audio" | "display";
const PANELS: { id: Panel; label: string }[] = [
  { id: "audio", label: "Audio stream" },
  { id: "display", label: "Now playing page" },
];

function StreamUrlDialog({ streamUrl, onClose }: { streamUrl: string; onClose(): void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [options, setOptions] = useState(() => stored(OPTIONS_KEY, DEFAULT_STREAM_OPTIONS, validStream));
  const [radio, setRadio] = useState(() => stored(RADIO_OPTIONS_KEY, DEFAULT_RADIO_OPTIONS, validRadio));
  const [panel, setPanel] = useState<Panel>("audio");

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  function change(next: Partial<StreamOptions>) {
    const updated = { ...options, ...next };
    setOptions(updated);
    keep(OPTIONS_KEY, updated);
  }

  function changeRadio(next: Partial<RadioOptions>) {
    const updated = { ...radio, ...next };
    setRadio(updated);
    keep(RADIO_OPTIONS_KEY, updated);
  }

  const bitRateIndex = BIT_RATES.indexOf(options.bitRate as (typeof BIT_RATES)[number]);
  return (
    <dialog
      ref={dialog}
      className="stream-url-dialog"
      aria-labelledby="stream-url-dialog-title"
      // Closed by Done or Escape only: a click to come back to the window, on the backdrop,
      // does not lose the options being set.
      onClose={onClose}
    >
      <header className="stream-url-dialog__head">
        <h2 id="stream-url-dialog-title" className="stream-url-dialog__title">
          Stream URL
        </h2>
        <button
          className="icon-button"
          type="button"
          aria-label="Close"
          title="Close"
          onClick={() => dialog.current?.close()}
        >
          <RemoveIcon />
        </button>
      </header>
      <nav className="tabs stream-url-dialog__tabs" role="tablist" aria-label="Stream URL">
        {PANELS.map((p) => (
          <button
            key={p.id}
            type="button"
            role="tab"
            aria-selected={panel === p.id}
            className={`tabs__tab${panel === p.id ? " tabs__tab--active" : ""}`}
            onClick={() => setPanel(p.id)}
          >
            {p.label}
          </button>
        ))}
      </nav>

      {panel === "audio" ? (
        <>
          <p className="text-muted">For VLC or an internet radio app. Anyone with it can listen.</p>

          <label className="field">
            <span className="field__label">
              Quality: <strong>{options.bitRate} kbps</strong>
              {options.bitRate === DEFAULT_BIT_RATE && " (default)"}
            </span>
            <input
              className="slider"
              type="range"
              min={0}
              max={BIT_RATES.length - 1}
              step={1}
              aria-label="Quality"
              aria-valuetext={`${options.bitRate} kbps`}
              value={bitRateIndex}
              onChange={(e) => change({ bitRate: BIT_RATES[Number(e.target.value)] ?? DEFAULT_BIT_RATE })}
            />
            <span className="stream-url-dialog__note">Lower: less data, for a slow connection.</span>
          </label>

          <label className="field">
            <span className="field__label">
              Buffer on connect: <strong>{options.burst} s</strong>
            </span>
            <input
              className="slider"
              type="range"
              min={0}
              max={MAX_BURST}
              step={0.5}
              aria-label="Buffer on connect"
              aria-valuetext={`${options.burst} seconds`}
              value={options.burst}
              onChange={(e) => change({ burst: Number(e.target.value) })}
            />
            <span className="stream-url-dialog__note">
              Sent at once when a device connects. Higher: no pause at the start on apps with a large buffer (8 s for
              most), but the device hears the server player that much later.
            </span>
          </label>

          <label className="checkbox">
            <input type="checkbox" checked={options.titles} onChange={(e) => change({ titles: e.target.checked })} />
            <span>Send the title playing (internet radio apps show it)</span>
          </label>

          <UrlRow label="Stream URL" url={streamUrlWith(streamUrl, options)} />
        </>
      ) : (
        <>
          <p className="text-muted">
            What plays and what comes next, for a screen or a web page. Anyone with the link can see it.
          </p>

          <div className="stream-url-dialog__choices">
            <label className="field">
              <span className="field__label">Style</span>
              <select
                className="field__input"
                value={radio.layout}
                onChange={(e) => changeRadio({ layout: e.target.value as RadioOptions["layout"] })}
              >
                <option value="card">Card</option>
                <option value="banner">Banner</option>
              </select>
            </label>
            <label className="field">
              <span className="field__label">Theme</span>
              <select
                className="field__input"
                value={radio.theme}
                onChange={(e) => changeRadio({ theme: e.target.value as RadioOptions["theme"] })}
              >
                <option value="auto">Automatic</option>
                <option value="dark">Dark</option>
                <option value="light">Light</option>
              </select>
            </label>
            <label className="field">
              <span className="field__label">Accent</span>
              <select className="field__input" value={radio.accent} onChange={(e) => changeRadio({ accent: e.target.value })}>
                {ACCENTS.map((accent) => (
                  <option key={accent.id} value={accent.id}>
                    {accent.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">Shape</span>
              <select
                className="field__input"
                value={radio.ratio}
                disabled={radio.layout === "banner"}
                title={radio.layout === "banner" ? "The card's (a banner is one line)" : undefined}
                onChange={(e) => changeRadio({ ratio: e.target.value as RadioOptions["ratio"] })}
              >
                {RADIO_RATIOS.map((ratio) => (
                  <option key={ratio} value={ratio}>
                    {SHAPE_LABELS[ratio]}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">Size</span>
              <select
                className="field__input"
                value={radio.width}
                onChange={(e) => changeRadio({ width: Number(e.target.value) })}
              >
                {(WIDTHS.includes(radio.width) ? WIDTHS : [...WIDTHS, radio.width]).map((width) => (
                  <option key={width} value={width}>
                    {width === 0 ? "Fill window" : `${width} px wide`}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <span className="stream-url-dialog__hint">
            A shape and a size for a screen of a known resolution: the card is scaled to it, the height following
            from the shape.
          </span>

          <label className="field">
            <span className="field__label">
              Delay: <strong>{radio.delay} s</strong>
              {radio.delay !== options.burst && (
                <>
                  {" · "}
                  <button className="link-button" type="button" onClick={() => changeRadio({ delay: options.burst })}>
                    Same as the buffer ({options.burst} s)
                  </button>
                </>
              )}
            </span>
            <input
              className="slider"
              type="range"
              min={0}
              max={30}
              step={1}
              aria-label="Delay"
              aria-valuetext={`${radio.delay} seconds`}
              value={radio.delay}
              onChange={(e) => changeRadio({ delay: Number(e.target.value) })}
            />
            <span className="stream-url-dialog__note">
              Listeners hear the stream late (their buffer): the page shows the songs that much later, in step with them.
            </span>
          </label>

          <label className="field">
            <span className="field__label">
              Up next: <strong>{radio.upcoming === 0 ? "hidden" : `${radio.upcoming} songs`}</strong>
            </span>
            <input
              className="slider"
              type="range"
              min={0}
              max={MAX_SHOWN_UPCOMING}
              step={1}
              aria-label="Songs up next"
              aria-valuetext={radio.upcoming === 0 ? "hidden" : `${radio.upcoming} songs`}
              value={Math.min(radio.upcoming, MAX_SHOWN_UPCOMING)}
              onChange={(e) => changeRadio({ upcoming: Number(e.target.value) })}
            />
          </label>

          <label className="checkbox">
            <input type="checkbox" checked={radio.cover} onChange={(e) => changeRadio({ cover: e.target.checked })} />
            <span>Show the covers</span>
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={radio.listeners}
              onChange={(e) => changeRadio({ listeners: e.target.checked })}
            />
            <span>Show the number of listeners</span>
          </label>

          <UrlRow label="Now playing page" url={radioUrl(streamUrl, radio)} open />
          <span className="stream-url-dialog__hint">The same as plain text, for scripts and simple displays:</span>
          <UrlRow label="Now playing as text" url={radioTextUrl(streamUrl, radio)} />
        </>
      )}

      <div className="stream-url-dialog__actions">
        <button
          className="link-button"
          type="button"
          onClick={() => (panel === "audio" ? change(DEFAULT_STREAM_OPTIONS) : changeRadio(DEFAULT_RADIO_OPTIONS))}
        >
          Defaults
        </button>
        <button className="button button--primary" type="button" onClick={() => dialog.current?.close()}>
          Done
        </button>
      </div>
    </dialog>
  );
}

// The dialog lives at the app's root (StreamUrlDialogHost, in AppShell), not in the menu
// that opens it: that menu is in the queue panel, which closes when the mouse leaves it
// (leaving the window too) and is then inert, with all it holds.
let shown: string | null = null; // the stream's URL, while the dialog is open
const listeners = new Set<() => void>();

function setShown(streamUrl: string | null): void {
  shown = streamUrl;
  listeners.forEach((listener) => listener());
}

/** Opens the Stream URL dialog for the stream at `streamUrl`. */
export function showStreamUrlDialog(streamUrl: string): void {
  setShown(streamUrl);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Where the Stream URL dialog shows (once, at the app's root). */
export function StreamUrlDialogHost() {
  const streamUrl = useSyncExternalStore(subscribe, () => shown);
  return streamUrl ? <StreamUrlDialog streamUrl={streamUrl} onClose={() => setShown(null)} /> : null;
}
