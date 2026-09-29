// "Install as app": the web UI added to a phone's home screen (site.webmanifest), opening
// full screen without the browser's bars. Not an app to build: the browser does it.
//
// - Android (Chrome, Edge, Samsung Internet): the browser offers an install prompt
//   (`beforeinstallprompt`), kept here to be shown when the user asks.
// - iPhone / iPad: no prompt a page can open; the user adds it from the Share menu
//   ("Add to Home Screen"), so instructions are shown instead.

import { useSyncExternalStore } from "react";

/** Chrome's install prompt event (not in TypeScript's DOM types). */
interface InstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferred: InstallPromptEvent | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((listener) => listener());

/** Call once at start-up: the browser's event can come before any menu is shown. */
export function watchInstallPrompt(): void {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault(); // no mini-infobar: offered from the account menu instead
    deferred = event as InstallPromptEvent;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    notify();
  });
}

/** Already running from the home screen. */
export function isStandalone(): boolean {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

/** iPhone, iPad (iPadOS says it is a Mac, but has touch). */
export function isIos(): boolean {
  const ua = navigator.userAgent;
  return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}

function isTouchDevice(): boolean {
  return window.matchMedia?.("(pointer: coarse)").matches ?? false;
}

export type InstallMethod = "prompt" | "ios" | "manual" | null;

/** How the web UI can be installed here; null: already installed, or not a phone / tablet. */
export function installMethod(): InstallMethod {
  if (isStandalone()) return null;
  if (deferred) return "prompt";
  if (isIos()) return "ios";
  return isTouchDevice() ? "manual" : null;
}

export function useInstallMethod(): InstallMethod {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    installMethod,
  );
}

/** Opens the browser's install prompt; false if there is none (show instructions). */
export async function promptInstall(): Promise<boolean> {
  const event = deferred;
  if (!event) return false;
  deferred = null; // a prompt can be shown once
  notify();
  await event.prompt();
  return true;
}
