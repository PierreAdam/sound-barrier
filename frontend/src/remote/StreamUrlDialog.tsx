import { useEffect, useRef, useState } from "react";

import { CopyIcon } from "../components/Icons";
import {
  BIT_RATES,
  DEFAULT_BIT_RATE,
  DEFAULT_STREAM_OPTIONS,
  MAX_BURST,
  type StreamOptions,
  streamUrlWith,
} from "./streamUrl";

const OPTIONS_KEY = "sound-barrier.stream-url";

function storedOptions(): StreamOptions {
  try {
    const stored = JSON.parse(localStorage.getItem(OPTIONS_KEY) ?? "null") as Partial<StreamOptions> | null;
    const options = { ...DEFAULT_STREAM_OPTIONS, ...stored };
    const valid =
      (BIT_RATES as readonly number[]).includes(options.bitRate) &&
      typeof options.burst === "number" &&
      options.burst >= 0 &&
      options.burst <= MAX_BURST &&
      typeof options.titles === "boolean";
    return valid ? options : DEFAULT_STREAM_OPTIONS;
  } catch {
    return DEFAULT_STREAM_OPTIONS; // nothing kept, or private browsing
  }
}

/**
 * The server player's stream URL, with its options (quality, buffer, titles): for VLC or an
 * internet radio app. The options are kept in this browser.
 */
export function StreamUrlDialog({ streamUrl, onClose }: { streamUrl: string; onClose(): void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [options, setOptions] = useState(storedOptions);
  const [copied, setCopied] = useState(false);
  const url = streamUrlWith(streamUrl, options);

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  function change(next: Partial<StreamOptions>) {
    const updated = { ...options, ...next };
    setOptions(updated);
    setCopied(false);
    try {
      localStorage.setItem(OPTIONS_KEY, JSON.stringify(updated));
    } catch {
      // private browsing: only for this page
    }
  }

  async function copy() {
    await navigator.clipboard.writeText(url);
    setCopied(true);
  }

  const bitRateIndex = BIT_RATES.indexOf(options.bitRate as (typeof BIT_RATES)[number]);
  return (
    <dialog
      ref={dialog}
      className="stream-url-dialog"
      aria-labelledby="stream-url-dialog-title"
      onClose={onClose}
      // A click outside the box (on the backdrop) closes it.
      onClick={(event) => event.target === dialog.current && dialog.current.close()}
    >
      <h2 id="stream-url-dialog-title" className="stream-url-dialog__title">
        Stream URL
      </h2>
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

      <div className="stream-url-dialog__url">
        <input
          className="field__input"
          type="text"
          readOnly
          aria-label="Stream URL"
          value={url}
          onFocus={(e) => e.target.select()}
        />
        <button className="button button--ghost" type="button" onClick={() => void copy()}>
          <CopyIcon /> {copied ? "Copied" : "Copy"}
        </button>
      </div>

      <div className="stream-url-dialog__actions">
        <button className="link-button" type="button" onClick={() => change(DEFAULT_STREAM_OPTIONS)}>
          Defaults
        </button>
        <button className="button button--primary" type="button" onClick={() => dialog.current?.close()}>
          Done
        </button>
      </div>
    </dialog>
  );
}
