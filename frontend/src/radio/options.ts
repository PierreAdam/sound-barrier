/**
 * The radio page's options (radio.html, at /radio/<key>): what a server player plays, for
 * a screen or a web page. They are in its URL, built by the Stream URL dialog.
 */

import { ACCENTS } from "../theme/appearance";

export type RadioLayout = "card" | "banner";
export type RadioTheme = "auto" | "dark" | "light";
/** The card's shape: "auto" follows its content; the others are width:height. */
export const RADIO_RATIOS = ["auto", "1:1", "4:3", "16:9", "3:4"] as const;
export type RadioRatio = (typeof RADIO_RATIOS)[number];

export interface RadioOptions {
  layout: RadioLayout;
  theme: RadioTheme;
  accent: string; // one of ACCENTS
  upcoming: number; // songs shown after the current one
  delay: number; // seconds: what the listeners hear, that late (their buffer)
  cover: boolean;
  listeners: boolean;
  ratio: RadioRatio; // the card's shape
  width: number; // px, the height following from the shape; 0: fills the window
}

export const MAX_UPCOMING = 20; // as the backend's (services/server_player.py)
export const MAX_DELAY = 60;
export const MAX_WIDTH = 4096;

export const DEFAULT_RADIO_OPTIONS: RadioOptions = {
  layout: "card",
  theme: "auto",
  accent: "teal",
  upcoming: 3,
  delay: 0,
  cover: true,
  listeners: true,
  ratio: "auto",
  width: 0,
};

function number(value: string | null, max: number, fallback: number): number {
  const parsed = value === null ? NaN : Number(value);
  return Number.isFinite(parsed) ? Math.min(Math.max(parsed, 0), max) : fallback;
}

/** The stream's key and the options, from the page's URL (/radio/<key>?…, or ?key=). */
export function parseRadioUrl(href: string): { key: string | null; options: RadioOptions } {
  const url = new URL(href);
  const fromPath = /^\/radio\/([^/]+)\/?$/.exec(url.pathname)?.[1];
  const key = fromPath ? decodeURIComponent(fromPath) : url.searchParams.get("key");
  const get = (name: string) => url.searchParams.get(name);
  const d = DEFAULT_RADIO_OPTIONS;
  return {
    key: key || null,
    options: {
      layout: get("layout") === "banner" ? "banner" : "card",
      theme: get("theme") === "dark" || get("theme") === "light" ? (get("theme") as RadioTheme) : "auto",
      accent: ACCENTS.some((a) => a.id === get("accent")) ? (get("accent") as string) : d.accent,
      upcoming: Math.round(number(get("next"), MAX_UPCOMING, d.upcoming)),
      delay: number(get("delay"), MAX_DELAY, d.delay),
      cover: get("cover") !== "0",
      listeners: get("listeners") !== "0",
      ratio: RADIO_RATIOS.includes(get("ratio") as RadioRatio) ? (get("ratio") as RadioRatio) : d.ratio,
      width: Math.round(number(get("width"), MAX_WIDTH, d.width)),
    },
  };
}

/** The radio page of the stream at `streamUrl` (…/api/stream/<key>): the options changed
 * from the defaults only. */
export function radioUrl(streamUrl: string, options: RadioOptions): string {
  const stream = new URL(streamUrl);
  const key = stream.pathname.split("/").pop() ?? "";
  const url = new URL(`/radio/${encodeURIComponent(key)}`, stream.origin);
  const d = DEFAULT_RADIO_OPTIONS;
  if (options.layout !== d.layout) url.searchParams.set("layout", options.layout);
  if (options.theme !== d.theme) url.searchParams.set("theme", options.theme);
  if (options.accent !== d.accent) url.searchParams.set("accent", options.accent);
  if (options.upcoming !== d.upcoming) url.searchParams.set("next", String(options.upcoming));
  if (options.delay !== d.delay) url.searchParams.set("delay", String(options.delay));
  if (!options.cover) url.searchParams.set("cover", "0");
  if (!options.listeners) url.searchParams.set("listeners", "0");
  if (options.ratio !== d.ratio) url.searchParams.set("ratio", options.ratio);
  if (options.width !== d.width) url.searchParams.set("width", String(options.width));
  return url.toString();
}

/** The same as a few lines of plain text (for scripts and simple displays). */
export function radioTextUrl(streamUrl: string, options: RadioOptions): string {
  const url = new URL(`${streamUrl.replace(/\/$/, "")}/info`);
  url.searchParams.set("format", "text");
  if (options.upcoming !== DEFAULT_RADIO_OPTIONS.upcoming) url.searchParams.set("next", String(options.upcoming));
  if (options.delay > 0) url.searchParams.set("delay", String(options.delay));
  return url.toString();
}
