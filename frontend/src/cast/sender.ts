// Google Cast sender (Chrome / Edge only): tells a Chromecast to play a URL. The device
// then fetches the stream itself, from the server; this page can close. The receiver is
// Google's Default Media Receiver (the sound only: nothing to register or host), or
// Sound-Barrier's own (public/cast/receiver.html: a "Now playing" screen on the TV), once
// its Cast app id is set (Settings → External services).
//
// The SDK is loaded on first use. Only the few parts used here are declared (no npm types).

const SDK_URL = "https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1";
export const DEFAULT_RECEIVER = "CC1AD845"; // chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID
// DashCast: a published receiver that opens a web page (Home Assistant's dashboards use
// it). The Now playing screen without a receiver of our own: its page is given our page's
// address (with the stream's key, so a third party sees it).
const DASHCAST = "84912283";
const DASHCAST_NAMESPACE = "urn:x-cast:com.madmod.dashcast";

interface CastSession {
  loadMedia(request: unknown): Promise<unknown>;
  sendMessage(namespace: string, message: unknown): Promise<unknown>;
  getCastDevice(): { friendlyName: string };
}

interface CastContext {
  setOptions(options: { receiverApplicationId: string; autoJoinPolicy: string }): void;
  requestSession(): Promise<unknown>;
  getCurrentSession(): CastSession | null;
  endCurrentSession(stopCasting: boolean): void;
  getCastState(): string;
  addEventListener(type: string, listener: (event: { castState: string }) => void): void;
}

interface CastGlobals {
  cast: { framework: { CastContext: { getInstance(): CastContext }; CastContextEventType: { CAST_STATE_CHANGED: string } } };
  chrome: {
    cast: {
      AutoJoinPolicy: { ORIGIN_SCOPED: string };
      Image: new (url: string) => unknown;
      media: {
        MediaInfo: new (url: string, contentType: string) => { streamType: string; metadata: unknown };
        GenericMediaMetadata: new () => { title: string; subtitle: string; images: unknown[] };
        LoadRequest: new (media: unknown) => { autoplay: boolean };
        StreamType: { LIVE: string };
      };
    };
  };
  __onGCastApiAvailable?: (available: boolean) => void;
}

/** NO_DEVICES_AVAILABLE, NOT_CONNECTED, CONNECTING, CONNECTED; "UNAVAILABLE": no Cast here. */
export type CastState = "UNAVAILABLE" | "NO_DEVICES_AVAILABLE" | "NOT_CONNECTED" | "CONNECTING" | "CONNECTED";

let loading: Promise<CastGlobals | null> | null = null;
const listeners = new Set<(state: CastState) => void>();
let current: CastState = "UNAVAILABLE";
let receiver = DEFAULT_RECEIVER; // the app the Cast context is set up for

function globals(): CastGlobals {
  return window as unknown as CastGlobals;
}

/** Loads the SDK once; null where Cast is not supported (Firefox, Safari, iPhone). */
export function loadCast(): Promise<CastGlobals | null> {
  if (loading) return loading;
  loading = new Promise((resolve) => {
    const g = globals();
    const isChromium = /Chrome\/|Edg\//.test(navigator.userAgent) && !/CriOS|EdgiOS/.test(navigator.userAgent);
    if (!isChromium || !window.isSecureContext) {
      resolve(null);
      return;
    }
    g.__onGCastApiAvailable = (available) => {
      if (!available) {
        resolve(null);
        return;
      }
      const context = g.cast.framework.CastContext.getInstance();
      context.setOptions({
        receiverApplicationId: DEFAULT_RECEIVER,
        autoJoinPolicy: g.chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
      });
      const update = (state: string) => {
        current = state as CastState;
        listeners.forEach((listener) => listener(current));
      };
      context.addEventListener(g.cast.framework.CastContextEventType.CAST_STATE_CHANGED, (e) => update(e.castState));
      update(context.getCastState());
      resolve(g);
    };
    const script = document.createElement("script");
    script.src = SDK_URL;
    script.async = true;
    script.onerror = () => resolve(null);
    document.head.appendChild(script);
  });
  return loading;
}

export function castState(): CastState {
  return current;
}

export function onCastState(listener: (state: CastState) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Why a cast did not start, in words (the SDK rejects with an error code). */
function castError(code: unknown, custom: boolean): Error | null {
  const text = typeof code === "string" ? code : code instanceof Error ? code.message : String(code);
  if (text === "cancel") return null; // the picker closed, nothing chosen
  if (custom && (text === "receiver_unavailable" || text === "session_error" || text === "timeout")) {
    return new Error(
      "This device could not open the Now playing screen (its Cast app not published yet, or this " +
        "Chromecast not registered to test it): try “Cast audio only”",
    );
  }
  if (text === "receiver_unavailable") return new Error("No Cast device found on this network");
  return new Error(`Casting failed (${text})`);
}

/**
 * Asks the user for a device (Chrome's picker: call it from a click), then has it play
 * the live stream at `url`, on the receiver `appId` (Google's default one when not given:
 * the sound only). Returns the device's name, null when no device was chosen.
 */
export async function castStream(
  url: string,
  title: string,
  subtitle: string,
  appId: string = DEFAULT_RECEIVER,
): Promise<string | null> {
  const g = await loadCast();
  if (!g) throw new Error("Casting needs Chrome or Edge (not on iPhone), on an HTTPS page");
  const context = g.cast.framework.CastContext.getInstance();
  // Another receiver: set up for it (the picker then lists the devices that can run it).
  if (appId !== receiver) {
    if (context.getCurrentSession()) context.endCurrentSession(true);
    context.setOptions({ receiverApplicationId: appId, autoJoinPolicy: g.chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED });
    receiver = appId;
  }
  if (!context.getCurrentSession()) {
    try {
      await context.requestSession();
    } catch (e) {
      // Back to the default receiver: the devices it lists are those of most casts.
      if (appId !== DEFAULT_RECEIVER) {
        context.setOptions({
          receiverApplicationId: DEFAULT_RECEIVER,
          autoJoinPolicy: g.chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
        });
        receiver = DEFAULT_RECEIVER;
      }
      const error = castError(e, appId !== DEFAULT_RECEIVER);
      if (error) throw error;
      return null;
    }
  }
  const session = context.getCurrentSession();
  if (!session) throw new Error("No device chosen");
  const media = new g.chrome.cast.media.MediaInfo(url, "audio/mpeg");
  media.streamType = g.chrome.cast.media.StreamType.LIVE;
  const metadata = new g.chrome.cast.media.GenericMediaMetadata();
  metadata.title = title;
  metadata.subtitle = subtitle;
  metadata.images = [];
  media.metadata = metadata;
  const request = new g.chrome.cast.media.LoadRequest(media);
  request.autoplay = true;
  await session.loadMedia(request);
  return session.getCastDevice().friendlyName;
}

/** The Now playing page for a TV, following the stream at `streamUrl` (receiver.html). */
export function screenUrl(streamUrl: string): string {
  const origin = new URL(streamUrl).origin;
  return `${origin}/cast/receiver.html?stream=${encodeURIComponent(streamUrl)}&autoplay=1`;
}

/**
 * The Now playing screen through DashCast: the Chromecast opens our page itself, which
 * plays the stream (no receiver of our own needed). Returns the device's name, null when
 * no device was chosen.
 */
export async function castScreenWithDashCast(streamUrl: string): Promise<string | null> {
  const g = await loadCast();
  if (!g) throw new Error("Casting needs Chrome or Edge (not on iPhone), on an HTTPS page");
  const context = g.cast.framework.CastContext.getInstance();
  if (receiver !== DASHCAST) {
    if (context.getCurrentSession()) context.endCurrentSession(true);
    context.setOptions({ receiverApplicationId: DASHCAST, autoJoinPolicy: g.chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED });
    receiver = DASHCAST;
  }
  try {
    if (!context.getCurrentSession()) await context.requestSession();
  } catch (e) {
    context.setOptions({ receiverApplicationId: DEFAULT_RECEIVER, autoJoinPolicy: g.chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED });
    receiver = DEFAULT_RECEIVER;
    const code = typeof e === "string" ? e : e instanceof Error ? e.message : String(e);
    if (code === "cancel") return null; // the picker closed, nothing chosen
    throw new Error(`This device could not open the Now playing screen (DashCast: ${code}): try “Cast audio only”`);
  }
  const session = context.getCurrentSession();
  if (!session) return null;
  // `force`: the page itself, not in DashCast's frame (where sound may not start on its own).
  await session.sendMessage(DASHCAST_NAMESPACE, { url: screenUrl(streamUrl), force: true, reload: false, reload_time: 0 });
  return session.getCastDevice().friendlyName;
}

/** Stops the device (the server player keeps its queue). */
export async function stopCasting(): Promise<void> {
  const g = await loadCast();
  g?.cast.framework.CastContext.getInstance().endCurrentSession(true);
}
