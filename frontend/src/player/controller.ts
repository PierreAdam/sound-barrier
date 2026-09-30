// What the web UI drives: this tab's own player (PlayerEngine), or, in remote mode, a
// mirror of another player (remote/RemoteController.ts: another tab, or a server player)
// whose commands go over the remote control's WebSocket. Pages, the player bar and the
// queue panel only know this interface (usePlayer), so they work the same with both.

import type { AudioLike, PlayerSnapshot, Track } from "./engine";

export interface PlayerController {
  subscribe(listener: () => void): () => void;
  getSnapshot(): PlayerSnapshot;
  /** The exact position in seconds (the snapshot's is updated a few times a second). */
  readonly currentTime: number;
  readonly playbackRate: number;
  /** The audio elements playing here (visualizer): none for a remote player. */
  readonly audioElements: readonly AudioLike[];

  playQueue(tracks: Track[], startIndex?: number, startAt?: number): void;
  add(tracks: Track[]): void;
  playNext(tracks: Track[]): void;
  /** Queue positions, in play order. */
  remove(positions: number[]): void;
  move(from: number, to: number): void;
  clear(): void;
  undo(): void;
  playAt(index: number): void;

  togglePlay(): void;
  pause(): void;
  next(): void;
  previous(): void;
  seek(seconds: number): void;
  setPauseAtEnd(enabled: boolean): void;
  setVolume(volume: number): void;
  toggleMute(): void;
  toggleShuffle(): void;
  cycleRepeat(): void;
  toggleCrossfade(): void;
  setCrossfade(enabled: boolean): void;
  setCrossfadeSeconds(seconds: number): void;
  setSpokenSpeed(speed: number): void;
}
