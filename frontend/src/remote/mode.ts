import { useSyncExternalStore } from "react";

import type { TargetKind } from "./protocol";

// Where this tab's player bar and queue panel play: here, or on another player (remote
// mode: they mirror it, see RemoteController). Being controllable is apart (target.ts):
// the Remote menu never has both on. Kept in memory: a reloaded page plays here.

export type PlayerMode =
  | { kind: "local" }
  | { kind: "remote"; target: string; name: string; targetKind: TargetKind };

let mode: PlayerMode = { kind: "local" };
let notice: string | null = null; // e.g. the target went away
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

export function getPlayerMode(): PlayerMode {
  return mode;
}

export function controlTarget(target: string, name: string, targetKind: TargetKind): void {
  mode = { kind: "remote", target, name, targetKind };
  notice = null;
  emit();
}

/** Back to this tab's own player (paused, as it was left). */
export function playHere(why: string | null = null): void {
  if (mode.kind === "local" && notice === why) return;
  mode = { kind: "local" };
  notice = why;
  emit();
}

/** A notice about what plays, without leaving remote mode (e.g. the TV page waits). */
export function setModeNotice(text: string | null): void {
  notice = text;
  emit();
}

export function getModeNotice(): string | null {
  return notice;
}

export function dismissModeNotice(): void {
  notice = null;
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function usePlayerMode(): PlayerMode {
  return useSyncExternalStore(subscribe, getPlayerMode);
}

export function useModeNotice(): string | null {
  return useSyncExternalStore(subscribe, getModeNotice);
}
