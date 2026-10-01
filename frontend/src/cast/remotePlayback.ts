// Where Google's Cast SDK is not there (phones): the browser's own way of playing a media
// element on another device. Chrome on Android casts to a Chromecast with the Remote
// Playback API; Safari (iPhone, iPad, Mac) to an AirPlay device with its own AirPlay
// picker (its Remote Playback API refuses a stream not loaded yet).
//
// And VLC, which casts a stream to a Chromecast itself: the only way from an iPhone.

interface RemotePlayback extends EventTarget {
  readonly state: "disconnected" | "connecting" | "connected";
  prompt(): Promise<void>;
}

/** Safari's own AirPlay picker (older than the Remote Playback API). */
interface WebKitAirPlay {
  webkitShowPlaybackTargetPicker?(): void;
  readonly webkitCurrentPlaybackTargetIsWireless?: boolean;
}

type RemoteAudio = HTMLAudioElement & { remote?: RemotePlayback } & WebKitAirPlay;

let audio: RemoteAudio | null = null;
// Safari: the picker was closed without a device (it does not tell): stopped after this.
const AIRPLAY_WAIT_MS = 60_000;
const AIRPLAY_CHANGED = "webkitcurrentplaybacktargetiswirelesschanged";

const isApple = () => /iPhone|iPad|Macintosh/.test(navigator.userAgent) && !/Chrome\/|CriOS/.test(navigator.userAgent);

/** "Cast…" (Chrome: a Chromecast), "AirPlay…" (Safari), or null: not in this browser. */
export function remotePlaybackLabel(): string | null {
  if (typeof HTMLMediaElement === "undefined" || !("remote" in HTMLMediaElement.prototype)) return null;
  return isApple() ? "AirPlay…" : "Cast…";
}

/**
 * Asks the browser for a device (its own picker: call it from a tap), then plays `url`
 * there. The element stays while the page is open: the browser keeps the connection.
 * False: the picker was closed without a device.
 */
export async function playOnDevice(url: string): Promise<boolean> {
  if (!audio) {
    audio = document.createElement("audio") as RemoteAudio;
    audio.preload = "none";
    audio.hidden = true;
    document.body.appendChild(audio);
    const element = audio;
    element.remote?.addEventListener("connect", () => void element.play().catch(() => undefined));
    element.remote?.addEventListener("disconnect", () => element.pause());
    // Safari: AirPlay stopped (back on the iPad / iPhone): not played here.
    element.addEventListener(AIRPLAY_CHANGED, () => !element.webkitCurrentPlaybackTargetIsWireless && element.pause());
  }
  if (audio.src !== url) audio.src = url;
  // Safari: its AirPlay picker. Its `remote.prompt()` refuses an element that has not
  // loaded the stream yet (NotSupportedError), and iPadOS / iOS load nothing before a tap.
  if (isApple() && typeof audio.webkitShowPlaybackTargetPicker === "function") return airPlay(audio);
  if (!audio.remote) throw new Error("This browser cannot play on another device");
  try {
    await audio.remote.prompt();
    return true;
  } catch (e) {
    const name = e instanceof DOMException ? e.name : "";
    if (name === "NotAllowedError" || name === "AbortError") return false; // the picker closed
    if (name === "NotFoundError") throw new Error("No device found on this network");
    if (name === "NotSupportedError") throw new Error("This browser cannot play this stream on another device");
    throw e;
  }
}

/**
 * Safari: plays the stream muted (started in the tap: allowed) and opens the AirPlay
 * picker; unmuted once on an AirPlay device. Safari does not tell when its picker closes
 * without one: the muted stream then stops after a while. True at once: the picker is open.
 */
let airPlayWait: (() => void) | null = null;

function airPlay(element: RemoteAudio): Promise<boolean> {
  airPlayWait?.(); // an earlier picker left open: this one replaces it
  element.muted = true;
  void element.play().catch(() => undefined);
  element.webkitShowPlaybackTargetPicker?.();
  const finish = (chosen: boolean) => {
    window.clearTimeout(timer);
    element.removeEventListener(AIRPLAY_CHANGED, changed);
    airPlayWait = null;
    if (chosen) element.muted = false;
    else element.pause();
  };
  const changed = () => element.webkitCurrentPlaybackTargetIsWireless && finish(true);
  const timer = window.setTimeout(() => finish(false), AIRPLAY_WAIT_MS);
  element.addEventListener(AIRPLAY_CHANGED, changed);
  airPlayWait = () => {
    window.clearTimeout(timer);
    element.removeEventListener(AIRPLAY_CHANGED, changed);
  };
  if (element.webkitCurrentPlaybackTargetIsWireless) finish(true); // already on AirPlay
  return Promise.resolve(true);
}

/** Stops what `playOnDevice` started. */
export function stopDevice(): void {
  airPlayWait?.();
  airPlayWait = null;
  if (!audio) return;
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
}

/** A phone: VLC may be there, and cast the stream itself (to a Chromecast too). */
export function vlcLink(url: string): string | null {
  const ua = navigator.userAgent;
  if (/iPhone|iPad/.test(ua)) return `vlc-x-callback://x-callback-url/stream?url=${encodeURIComponent(url)}`;
  if (/Android/.test(ua)) {
    const { protocol, host, pathname, search } = new URL(url);
    return `intent://${host}${pathname}${search}#Intent;scheme=${protocol.slice(0, -1)};package=org.videolan.vlc;type=audio/mpeg;end`;
  }
  return null;
}
