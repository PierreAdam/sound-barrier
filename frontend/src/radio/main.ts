// The radio page (radio.html, at /radio/<key>): a server player's "now playing", for a
// screen or a web page. It asks the backend what plays every few seconds (and when the
// song should end), and moves the progress bar in between on its own clock.

import { formatTime } from "../format";
import "../theme/theme.less";
import { parseRadioUrl, type RadioOptions, type RadioRatio } from "./options";

const POLL_MS = 5000;
const TICK_MS = 1000; // the elapsed time's text
const RETRY_MS = 10000; // the server out of reach
const CARD_WIDTH = 560; // px: the card as designed, with its shape "auto"
// The card of each shape as designed (px), then scaled to its size: text and covers keep
// their proportions at any size (a screen's fixed resolution).
const SHAPES: Record<Exclude<RadioRatio, "auto">, { width: number; height: number; kind: string }> = {
  "1:1": { width: 560, height: 560, kind: "square" },
  "4:3": { width: 640, height: 480, kind: "square" },
  "16:9": { width: 800, height: 450, kind: "wide" },
  "3:4": { width: 480, height: 640, kind: "tall" },
};

interface OnAirTrack {
  title: string;
  artist: string | null;
  album: string | null;
  year: number | null;
  coverArt: string | null;
  duration: number;
}

interface OnAir {
  station: string;
  playing: boolean;
  track: OnAirTrack | null;
  position: number;
  duration: number;
  chapter: string | null;
  upcoming: OnAirTrack[];
  listeners: number;
}

const el = Object.fromEntries(
  ["radio", "idle", "state", "station", "listeners", "cover", "title", "artist", "bar", "elapsed", "duration", "next", "upcoming"].map(
    (id) => [id, document.getElementById(id) as HTMLElement],
  ),
) as Record<string, HTMLElement>;

const { key, options } = parseRadioUrl(location.href);
let onAir: OnAir | null = null;
let receivedAt = 0; // performance.now() when `onAir` came
let timer: number | undefined;
let shownUpcoming = ""; // the list shown, as JSON
let barStart: number | null = null; // the song's position where the bar's animation starts

function applyTheme({ theme, accent }: RadioOptions): void {
  const root = document.documentElement;
  const light = theme === "light" || (theme === "auto" && matchMedia("(prefers-color-scheme: light)").matches);
  root.dataset.theme = light ? "light" : "dark";
  root.dataset.accent = accent;
}

function idle(text: string): void {
  if (el.idle!.textContent !== text) el.idle!.textContent = text;
  if (el.idle!.hidden) el.idle!.hidden = false;
  if (!el.radio!.hidden) el.radio!.hidden = true;
}

function coverUrl(id: string, size: number): string {
  return `/api/stream/${encodeURIComponent(key ?? "")}/cover?id=${encodeURIComponent(id)}&size=${size}`;
}

function byline(track: OnAirTrack): string {
  const album = track.album ? `${track.album}${track.year ? ` (${track.year})` : ""}` : null;
  return [track.artist, album].filter(Boolean).join(" · ");
}

function setCover(img: HTMLImageElement, track: OnAirTrack, size: number): void {
  const src = options.cover && track.coverArt ? coverUrl(track.coverArt, size) : "";
  if (img.hidden !== !src) img.hidden = !src;
  if (src && img.getAttribute("src") !== src) img.src = src;
}

function upcomingItem(track: OnAirTrack): HTMLLIElement {
  const item = document.createElement("li");
  item.className = "radio__song";
  if (options.cover) {
    const img = document.createElement("img");
    img.className = "radio__song-cover";
    img.alt = "";
    setCover(img, track, 64);
    item.append(img);
  }
  const name = document.createElement("span");
  name.className = "radio__song-name";
  const title = document.createElement("span");
  title.className = "radio__song-title";
  title.textContent = track.title;
  name.append(title);
  if (track.artist) {
    const artist = document.createElement("span");
    artist.className = "radio__song-artist";
    artist.textContent = ` · ${track.artist}`;
    name.append(artist);
  }
  const length = document.createElement("span");
  length.className = "radio__song-length";
  length.textContent = track.duration > 0 ? formatTime(track.duration) : "";
  item.append(name, length);
  return item;
}

/** Where the song is now: the backend's position, moved on by the time since. */
function position(): number {
  if (!onAir) return 0;
  const elapsed = onAir.playing ? (performance.now() - receivedAt) / 1000 : 0;
  const at = onAir.position + elapsed;
  return onAir.duration > 0 ? Math.min(at, onAir.duration) : at;
}

/** Changes a text only when it differs: an unchanged page is not laid out again. */
function setText(element: HTMLElement, text: string): void {
  if (element.textContent !== text) element.textContent = text;
}

function setHidden(element: HTMLElement, hidden: boolean): void {
  if (element.hidden !== hidden) element.hidden = hidden;
}

/** The elapsed time, once a second (the bar moves on its own: `follow`). */
function tick(): void {
  if (onAir?.track && document.visibilityState === "visible") setText(el.elapsed!, formatTime(position()));
}

/**
 * The bar: one animation from where the song is to its end, run by the browser's
 * compositor (a transform: nothing laid out, no script per frame). Started again only
 * when the song, its state or its pace changes, or when it drifts from the backend's.
 */
function follow(data: OnAir, changed: boolean): void {
  const bar = el.bar!;
  const at = data.duration > 0 ? Math.min(data.position / data.duration, 1) : 0;
  const expected = bar.getAnimations()[0]?.currentTime;
  const drift =
    typeof expected === "number" && barStart !== null
      ? Math.abs(barStart + expected / 1000 - data.position)
      : Infinity;
  if (!changed && data.playing && drift < 1) return;
  bar.getAnimations().forEach((animation) => animation.cancel());
  bar.style.transform = `scaleX(${at})`;
  barStart = null;
  if (!data.playing || data.duration <= 0 || at >= 1) return;
  barStart = data.position;
  bar.animate([{ transform: `scaleX(${at})` }, { transform: "scaleX(1)" }], {
    duration: (data.duration - data.position) * 1000,
    easing: "linear",
    fill: "forwards",
  });
}

function render(data: OnAir): void {
  const previous = onAir;
  onAir = data;
  receivedAt = performance.now();
  const track = data.track;
  if (!track) {
    follow(data, true);
    idle(`${data.station} · nothing playing`);
    return;
  }
  setHidden(el.idle!, true);
  setHidden(el.radio!, false);
  setText(el.state!, data.playing ? "Live" : "Paused");
  el.radio!.classList.toggle("radio--paused", !data.playing);
  setText(el.station!, data.station);
  setHidden(el.listeners!, !options.listeners);
  setText(el.listeners!, `${data.listeners} ${data.listeners === 1 ? "listener" : "listeners"}`);
  setCover(el.cover as HTMLImageElement, track, options.layout === "banner" ? 128 : 300);
  setText(el.title!, data.chapter ? `${track.title} · ${data.chapter}` : track.title);
  setText(el.artist!, byline(track));
  setText(el.duration!, formatTime(data.duration));
  // The list only when it changed (its covers would be drawn again).
  const upcoming = JSON.stringify(data.upcoming);
  if (upcoming !== shownUpcoming) {
    shownUpcoming = upcoming;
    setHidden(el.next!, data.upcoming.length === 0);
    el.upcoming!.replaceChildren(...data.upcoming.map(upcomingItem));
  }
  const title = `${track.artist ? `${track.artist} - ` : ""}${track.title} · ${data.station}`;
  if (document.title !== title) document.title = title;
  const changed =
    !previous?.track ||
    previous.track.title !== track.title ||
    previous.track.coverArt !== track.coverArt ||
    previous.playing !== data.playing ||
    previous.duration !== data.duration;
  follow(data, changed);
  tick();
}

async function poll(): Promise<void> {
  window.clearTimeout(timer);
  let wait = POLL_MS;
  try {
    const params = new URLSearchParams({ next: String(options.upcoming), delay: String(options.delay) });
    const response = await fetch(`/api/stream/${encodeURIComponent(key ?? "")}/info?${params}`, { cache: "no-store" });
    if (response.status === 404) {
      onAir = null;
      shownUpcoming = "";
      idle("This stream has ended");
      wait = RETRY_MS; // the server player may start again (a new key, though)
    } else if (response.ok) {
      const data = (await response.json()) as OnAir;
      render(data);
      // Asked again right after the song ends: the next one shows at once.
      const left = data.playing && data.duration > 0 ? data.duration - data.position : Infinity;
      wait = Math.max(500, Math.min(POLL_MS, left * 1000 + 300));
    } else {
      wait = RETRY_MS;
    }
  } catch {
    wait = RETRY_MS; // offline: the last answer stays
  }
  timer = window.setTimeout(() => void poll(), wait);
}

/** The card at its size: the given width, else the largest that fits the window. */
function fit(): void {
  const card = el.radio!;
  if (options.layout === "banner") {
    card.style.maxWidth = options.width > 0 ? `${options.width}px` : "";
    return;
  }
  if (options.ratio === "auto") {
    card.style.zoom = options.width > 0 ? String(options.width / CARD_WIDTH) : "";
    return;
  }
  const shape = SHAPES[options.ratio];
  card.style.width = `${shape.width}px`;
  card.style.height = `${shape.height}px`;
  const scale =
    options.width > 0
      ? options.width / shape.width
      : Math.min(innerWidth / shape.width, innerHeight / shape.height);
  card.style.zoom = String(scale);
}

applyTheme(options);
document.body.classList.add(`radio-page--${options.layout}`);
el.radio!.classList.add(`radio--${options.layout}`);
if (!options.cover) el.radio!.classList.add("radio--no-cover");
if (options.layout === "card" && options.ratio !== "auto") {
  el.radio!.classList.add("radio--shaped", `radio--${SHAPES[options.ratio].kind}`);
  document.body.classList.add("radio-page--shaped");
}
fit();
window.addEventListener("resize", fit);
if (key) {
  void poll();
  window.setInterval(tick, TICK_MS);
} else {
  idle("No stream given: open the link from Sound-Barrier's Stream URL");
}
