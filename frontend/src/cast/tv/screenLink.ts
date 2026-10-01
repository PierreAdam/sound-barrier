// This tab's side of its TV page (tv.html): the same interface as the remote control's
// link (remote/link.ts), so that remote mode drives the TV page as it drives another tab.
// Its one target is the TV page, "screen" kind.

import type { SubsonicClient } from "../../api/subsonic";
import type { QueueState } from "../../player/engine";
import type { LinkTarget, LinkView } from "../../remote/link";
import type { RemoteCommand, RemoteQueue, RemoteState } from "../../remote/protocol";
import type { ScreenChannel } from "./channel";

export const SCREEN_TARGET = "screen";

export type ScreenReport = { type: "state"; state: RemoteState } | { type: "queue"; queue: RemoteQueue };

export class ScreenLink {
  private channel: ScreenChannel | null = null;
  private listeners = new Set<() => void>();
  private view: LinkView = { connected: false, targets: null, queue: null, error: null };
  private target: LinkTarget | null = null;
  private queue: RemoteQueue | null = null;
  // What it played last: kept once it closed, to take it back here.
  private last: { queue: RemoteQueue; state: RemoteState; at: number } | null = null;
  // The TV page waits for a click to start the sound (true), or plays (false).
  private onBlocked: ((blocked: boolean) => void) | null = null;
  private blocked = false;
  // Its reports, also passed on to the user's other devices when this tab is controllable
  // (RemoteTargetBridge): the TV page speaks the remote control's protocol.
  private reportListeners = new Set<(report: ScreenReport) => void>();

  /**
   * Starts on a TV page just opened: hands it the credentials to play with, then the
   * commands (`first`: this tab's queue, to go on there).
   */
  start(
    channel: ScreenChannel,
    client: SubsonicClient,
    name: string,
    first: RemoteCommand[],
    blocked: (blocked: boolean) => void,
  ): void {
    this.stop(false);
    this.channel = channel;
    this.onBlocked = blocked;
    this.blocked = false;
    this.target = { id: SCREEN_TARGET, playerName: name, device: "This computer", kind: "screen", state: null, at: 0 };
    this.set({ connected: true, targets: [this.target], queue: null });
    let greeted = false;
    channel.onMessage((message) => {
      switch (message.type) {
        case "ready":
          if (greeted) break;
          greeted = true;
          channel.send({ type: "hello", credentials: client.sharedCredentials });
          for (const command of first) channel.send({ type: "command", command });
          break;
        case "state":
          if (!this.target) break;
          this.reportListeners.forEach((listener) => listener({ type: "state", state: message.state }));
          this.target = { ...this.target, state: message.state, at: Date.now() };
          if (this.queue) this.last = { queue: this.queue, state: message.state, at: Date.now() };
          if (this.blocked && message.state.playing) {
            this.blocked = false;
            this.onBlocked?.(false);
          }
          this.set({ targets: [this.target] });
          break;
        case "queue":
          this.queue = message.queue;
          this.reportListeners.forEach((listener) => listener({ type: "queue", queue: message.queue }));
          this.set({ queue: message.queue });
          break;
        case "blocked":
          this.blocked = true;
          this.onBlocked?.(true);
          break;
      }
    });
    // The TV page closed (the Chromecast stopped, the window closed): no target any more.
    channel.onClose(() => {
      if (this.channel !== channel) return;
      this.channel = null;
      this.target = null;
      this.set({ connected: false, targets: [] });
    });
  }

  /**
   * What the TV page played last, to take it back here (null: nothing known of it), and
   * whether it was playing. Its position: advanced since it said it.
   */
  takeBack(): { queue: QueueState; playing: boolean } | null {
    const last = this.last;
    if (!last) return null;
    const { queue, state, at } = last;
    const elapsed = state.playing ? ((Date.now() - at) / 1000) * state.rate : 0;
    const index = state.currentKey === null ? -1 : queue.keys.indexOf(state.currentKey);
    return {
      queue: { tracks: queue.tracks, originalOrder: null, index, position: state.position + elapsed },
      playing: state.playing,
    };
  }

  get active(): boolean {
    return this.channel !== null;
  }

  /** The TV page's reports (its queue, then its states), as they come. */
  onReport(listener: (report: ScreenReport) => void): () => void {
    this.reportListeners.add(listener);
    return () => this.reportListeners.delete(listener);
  }

  /** What the TV page reported last (to report it again: a new connection). */
  latest(): { queue: RemoteQueue | null; state: RemoteState | null } {
    return { queue: this.queue, state: this.target?.state ?? null };
  }

  /** Closes the TV page (`bye`: it closes itself; a presentation is ended from here). */
  stop(notify = true): void {
    const channel = this.channel;
    this.channel = null;
    if (channel) {
      if (notify) channel.send({ type: "bye" });
      channel.close();
    }
    this.target = null;
    this.queue = null;
    this.last = null;
    this.set({ connected: false, targets: [], queue: null });
  }

  // --- LinkLike (remote/RemoteController.ts) -----------------------------------------------

  acquire = (): (() => void) => () => undefined;

  watch = (): void => undefined;

  send = (_target: string, command: RemoteCommand): void => {
    this.channel?.send({ type: "command", command });
  };

  getView = (): LinkView => this.view;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private set(changes: Partial<LinkView>): void {
    this.view = { ...this.view, ...changes };
    this.listeners.forEach((listener) => listener());
  }
}

export const screenLink = new ScreenLink();
