// This tab and its TV page (tv.html): the TV page plays this tab's queue (its own player
// engine), this tab drives it in remote mode. Both run in this browser: nothing goes
// through a third party, nor through the server but the music itself.
//
// The TV page is opened either by Chrome's Presentation API (Chrome renders it in a tab
// of its own, out of sight, and mirrors it to a Chromecast), or in a window (a TV plugged
// in, a test). The messages are the same both ways.

import type { Credentials } from "../../api/subsonic";
import type { RemoteCommand, RemoteQueue, RemoteState } from "../../remote/protocol";

/** This tab → the TV page. */
export type ToScreen =
  | { type: "hello"; credentials: Credentials } // who plays: its Subsonic credentials
  | { type: "command"; command: RemoteCommand }
  | { type: "bye" }; // this tab plays again: the TV page closes

/** The TV page → this tab. */
export type FromScreen =
  | { type: "ready" } // loaded, waiting for "hello"
  | { type: "state"; state: RemoteState }
  | { type: "queue"; queue: RemoteQueue }
  | { type: "blocked" }; // the browser would not start the sound without a click there

export interface Channel<In, Out> {
  send(message: Out): void;
  onMessage(listener: (message: In) => void): void;
  onClose(listener: () => void): void;
  close(): void;
}

export type ScreenChannel = Channel<FromScreen, ToScreen>;
export type ControllerChannel = Channel<ToScreen, FromScreen>;

export const TV_URL = "/tv.html";
const WINDOW_NAME = "sound-barrier-tv";

function parse<T>(data: unknown): T | null {
  try {
    return (typeof data === "string" ? JSON.parse(data) : data) as T;
  } catch {
    return null;
  }
}

// --- the Presentation API --------------------------------------------------------------

interface PresentationConnectionLike extends EventTarget {
  readonly state: string;
  send(message: string): void;
  close(): void;
  terminate(): void;
}

type PresentationRequestClass = new (urls: string[]) => { start(): Promise<PresentationConnectionLike> };

function presentationRequest(): PresentationRequestClass | null {
  const Request = (window as unknown as { PresentationRequest?: PresentationRequestClass }).PresentationRequest;
  return typeof Request === "function" ? Request : null;
}

/** Desktop Chrome / Edge: a TV (Chromecast) can show a page rendered here. */
export function canCastScreen(): boolean {
  return !/Android|iPhone|iPad/.test(navigator.userAgent) && presentationRequest() !== null;
}

function overConnection<In, Out>(connection: PresentationConnectionLike, terminate: boolean): Channel<In, Out> {
  return {
    send: (message) => connection.state === "connected" && connection.send(JSON.stringify(message)),
    onMessage: (listener) =>
      connection.addEventListener("message", (event) => {
        const message = parse<In>((event as MessageEvent).data);
        if (message) listener(message);
      }),
    onClose: (listener) => {
      connection.addEventListener("close", listener);
      connection.addEventListener("terminate", listener);
    },
    close: () => (terminate ? connection.terminate() : connection.close()),
  };
}

/**
 * Asks for a TV (Chrome's picker: call it from a click), and shows the TV page there.
 * Null: no device chosen.
 */
export async function castScreen(): Promise<ScreenChannel | null> {
  const Request = presentationRequest();
  if (!Request) throw new Error("Casting this player needs Chrome or Edge on a computer");
  try {
    const connection = await new Request([new URL(TV_URL, location.href).href]).start();
    return overConnection<FromScreen, ToScreen>(connection, true);
  } catch (e) {
    const name = e instanceof DOMException ? e.name : "";
    if (name === "NotAllowedError" || name === "AbortError") return null; // the picker closed
    if (name === "NotFoundError") throw new Error("No device found that Chrome can show a page on");
    throw e;
  }
}

// --- a window ---------------------------------------------------------------------------

/** The TV page in a window of its own (a TV plugged in: drag it there, full screen). */
export function openScreenWindow(): ScreenChannel | null {
  const opened = window.open(TV_URL, WINDOW_NAME, "popup,width=1280,height=720");
  if (!opened) return null;
  const listeners: ((message: FromScreen) => void)[] = [];
  const closers: (() => void)[] = [];
  const onMessage = (event: MessageEvent) => {
    if (event.source !== opened || event.origin !== location.origin) return;
    const message = parse<FromScreen>(event.data);
    if (message) listeners.forEach((listener) => listener(message));
  };
  window.addEventListener("message", onMessage);
  // A window says nothing when it is closed: asked every second.
  const watch = setInterval(() => {
    if (!opened.closed) return;
    clearInterval(watch);
    window.removeEventListener("message", onMessage);
    closers.forEach((closer) => closer());
  }, 1000);
  return {
    send: (message) => !opened.closed && opened.postMessage(JSON.stringify(message), location.origin),
    onMessage: (listener) => listeners.push(listener),
    onClose: (listener) => closers.push(listener),
    close: () => opened.close(),
  };
}

// --- the TV page's side -----------------------------------------------------------------

/** The tab that opened this TV page: through the Presentation API, or as its window. */
export function connectToController(): Promise<ControllerChannel | null> {
  const receiver = (
    navigator as Navigator & {
      presentation?: {
        receiver?: {
          connectionList: Promise<{
            connections: PresentationConnectionLike[];
            addEventListener(type: string, listener: (event: Event) => void): void;
          }>;
        };
      };
    }
  ).presentation?.receiver;
  if (receiver) {
    return receiver.connectionList.then(
      (list) =>
        new Promise((resolve) => {
          const first = list.connections[0];
          if (first) resolve(overConnection<ToScreen, FromScreen>(first, false));
          else
            list.addEventListener("connectionavailable", (event) =>
              resolve(
                overConnection<ToScreen, FromScreen>(
                  (event as Event & { connection: PresentationConnectionLike }).connection,
                  false,
                ),
              ),
            );
        }),
    );
  }
  // Its window's opener; or, embedded in a page of this site (a test, a dashboard), that page.
  const opener = (window.opener as Window | null) ?? (window.parent !== window ? window.parent : null);
  if (!opener) return Promise.resolve(null);
  const listeners: ((message: ToScreen) => void)[] = [];
  window.addEventListener("message", (event: MessageEvent) => {
    if (event.source !== opener || event.origin !== location.origin) return;
    const message = parse<ToScreen>(event.data);
    if (message) listeners.forEach((listener) => listener(message));
  });
  return Promise.resolve({
    send: (message) => opener.postMessage(JSON.stringify(message), location.origin),
    onMessage: (listener) => listeners.push(listener),
    onClose: () => undefined, // this window closes itself
    close: () => window.close(),
  });
}
