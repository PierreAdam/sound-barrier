import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SubsonicClient } from "../../api/subsonic";
import type { Track } from "../../player/engine";
import type { RemoteState } from "../../remote/protocol";
import type { FromScreen, ScreenChannel, ToScreen } from "./channel";
import { SCREEN_TARGET, ScreenLink } from "./screenLink";

class FakeChannel implements ScreenChannel {
  sent: ToScreen[] = [];
  closed = false;
  private listeners: ((message: FromScreen) => void)[] = [];
  private closers: (() => void)[] = [];

  send(message: ToScreen): void {
    this.sent.push(message);
  }
  onMessage(listener: (message: FromScreen) => void): void {
    this.listeners.push(listener);
  }
  onClose(listener: () => void): void {
    this.closers.push(listener);
  }
  close(): void {
    this.closed = true;
  }
  /** The TV page says something. */
  receive(message: FromScreen): void {
    this.listeners.forEach((listener) => listener(message));
  }
  /** The TV page went away (its window closed, the Chromecast stopped). */
  vanish(): void {
    this.closers.forEach((closer) => closer());
  }
}

const tracks: Track[] = ["a", "b"].map((id) => ({ id, title: id.toUpperCase() }));
const client = new SubsonicClient({ username: "me", token: "t", salt: "s" });

/** A TV page's state: playing the second entry (key 1), 10 s in (only what is read here). */
function state(changes: Partial<RemoteState>): RemoteState {
  const base = { playing: true, position: 10, rate: 1, currentKey: 1, index: 1, queueRevision: 1 };
  return { ...base, ...changes } as RemoteState;
}

describe("ScreenLink", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("hands the TV page the credentials, then this tab's queue", () => {
    const link = new ScreenLink();
    const channel = new FakeChannel();
    const command = { name: "playQueue", tracks, index: 1, startAt: 42 } as const;
    link.start(channel, client, "TV", [command], () => undefined);
    expect(channel.sent).toEqual([]); // not before the page is ready
    channel.receive({ type: "ready" });
    expect(channel.sent).toEqual([
      { type: "hello", credentials: { username: "me", token: "t", salt: "s" } },
      { type: "command", command },
    ]);
    link.send(SCREEN_TARGET, { name: "next" });
    expect(channel.sent.at(-1)).toEqual({ type: "command", command: { name: "next" } });
  });

  it("mirrors what the TV page reports, and takes it back where it got to", () => {
    const link = new ScreenLink();
    const channel = new FakeChannel();
    link.start(channel, client, "TV", [], () => undefined);
    channel.receive({ type: "queue", queue: { revision: 1, keys: [0, 1], tracks } });
    channel.receive({ type: "state", state: state({}) });
    const view = link.getView();
    expect(view.targets?.map((t) => [t.id, t.kind])).toEqual([[SCREEN_TARGET, "screen"]]);
    expect(view.queue?.tracks.map((t) => t.id)).toEqual(["a", "b"]);

    vi.advanceTimersByTime(5000);
    // The page went away: no target any more, but what it played can still come back.
    channel.vanish();
    expect(link.getView().targets).toEqual([]);
    const back = link.takeBack();
    expect(back?.playing).toBe(true);
    expect(back?.queue.index).toBe(1);
    expect(back?.queue.position).toBeCloseTo(15, 0); // 10 s, and 5 s since
  });

  it("says when the TV page waits for a click, and when it plays", () => {
    const link = new ScreenLink();
    const channel = new FakeChannel();
    const blocked = vi.fn();
    link.start(channel, client, "TV", [], blocked);
    channel.receive({ type: "queue", queue: { revision: 1, keys: [0], tracks } });
    channel.receive({ type: "blocked" });
    expect(blocked).toHaveBeenLastCalledWith(true);
    channel.receive({ type: "state", state: state({}) });
    expect(blocked).toHaveBeenLastCalledWith(false);
  });

  it("stopping says bye and closes", () => {
    const link = new ScreenLink();
    const channel = new FakeChannel();
    link.start(channel, client, "TV", [], () => undefined);
    link.stop();
    expect(channel.sent.at(-1)).toEqual({ type: "bye" });
    expect(channel.closed).toBe(true);
    expect(link.takeBack()).toBeNull();
  });

  it("passes the TV page's reports on, and keeps the latest (this tab controllable)", () => {
    const link = new ScreenLink();
    const channel = new FakeChannel();
    link.start(channel, client, "TV", [], () => undefined);
    const reports: string[] = [];
    const stop = link.onReport((report) => reports.push(report.type));
    const queue = { revision: 1, keys: [0, 1], tracks };
    channel.receive({ type: "queue", queue });
    channel.receive({ type: "state", state: state({}) });
    expect(reports).toEqual(["queue", "state"]);
    expect(link.latest()).toEqual({ queue, state: state({}) });
    // A command from another device goes to the TV page as it is.
    link.send(SCREEN_TARGET, { name: "next" });
    expect(channel.sent.at(-1)).toEqual({ type: "command", command: { name: "next" } });
    stop();
    channel.receive({ type: "state", state: state({ playing: false }) });
    expect(reports).toEqual(["queue", "state"]);
    link.stop();
    expect(link.latest()).toEqual({ queue: null, state: null });
  });
});
