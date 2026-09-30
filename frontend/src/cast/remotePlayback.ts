// Where Google's Cast SDK is not there (phones): the browser's own way of playing a media
// element on another device, the Remote Playback API. Chrome on Android casts to a
// Chromecast with it, Safari (iPhone, Mac) to an AirPlay device. The device fetches the
// stream itself, from the server; nothing plays on the phone.
//
// And VLC, which casts a stream to a Chromecast itself: the only way from an iPhone.

interface RemotePlayback extends EventTarget {
  readonly state: "disconnected" | "connecting" | "connected";
  prompt(): Promise<void>;
}

type RemoteAudio = HTMLAudioElement & { remote?: RemotePlayback };

let audio: RemoteAudio | null = null;

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
  }
  if (audio.src !== url) audio.src = url;
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

/** Stops what `playOnDevice` started. */
export function stopDevice(): void {
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
