// The Now playing screen without any receiver on the Chromecast: Chrome (desktop) renders
// our page itself, in a tab of its own out of sight, and mirrors it to the TV (the
// Presentation API). Nothing leaves this computer and the server but that video: private.
// The computer must stay on, Chrome open.

interface PresentationConnection extends EventTarget {
  readonly state: "connecting" | "connected" | "closed" | "terminated";
  terminate(): void;
}

interface PresentationRequestLike {
  start(): Promise<PresentationConnection>;
}

type PresentationRequestClass = new (urls: string[]) => PresentationRequestLike;

let connection: PresentationConnection | null = null;

/** Desktop Chrome / Edge only (phones have no such thing for Cast devices). */
export function canPresent(): boolean {
  const mobile = /Android|iPhone|iPad/.test(navigator.userAgent);
  return !mobile && typeof (window as unknown as { PresentationRequest?: unknown }).PresentationRequest === "function";
}

/**
 * Asks for a device (Chrome's picker: call it from a click), then shows `url` there,
 * rendered here. False: no device chosen.
 */
export async function present(url: string): Promise<boolean> {
  const Request = (window as unknown as { PresentationRequest: PresentationRequestClass }).PresentationRequest;
  try {
    connection?.terminate();
    connection = await new Request([url]).start();
    return true;
  } catch (e) {
    const name = e instanceof DOMException ? e.name : "";
    if (name === "NotAllowedError" || name === "AbortError") return false; // the picker closed
    if (name === "NotFoundError") throw new Error("No device found that Chrome can show a page on");
    throw e;
  }
}

/** Stops what `present` started. */
export function stopPresenting(): void {
  connection?.terminate();
  connection = null;
}
