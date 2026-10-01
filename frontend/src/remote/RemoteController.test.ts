import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type AudioLike, PlayerEngine, type Track } from "../player/engine";
import { applyCommand, remoteStateOf } from "./apply";
import type { LinkView } from "./link";
import type { RemoteCommand } from "./protocol";
import { type LinkLike, RemoteController } from "./RemoteController";

class FakeAudio implements AudioLike {
  playbackRate = 1;
  defaultPlaybackRate = 1;
  src = "";
  currentTime = 0;
  duration = 200;
  volume = 1;
  muted = false;
  paused = true;
  readyState = 4;
  seeking = false;
  private listeners = new Map<string, Set<() => void>>();

  play(): Promise<void> {
    this.paused = false;
    this.fire("play");
    return Promise.resolve();
  }
  pause(): void {
    this.paused = true;
    this.fire("pause");
  }
  load(): void {}
  removeAttribute(): void {}
  addEventListener(type: string, listener: () => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(listener);
  }
  removeEventListener(type: string, listener: () => void): void {
    this.listeners.get(type)?.delete(listener);
  }
  fire(type: string): void {
    this.listeners.get(type)?.forEach((listener) => listener());
  }
}

const TARGET = "target-1";
const tracks: Track[] = ["a", "b", "c", "d"].map((id) => ({ id, title: id.toUpperCase() }));

/**
 * The link between a remote and a target tab, in memory: commands are applied to the
 * target's engine at once (as its bridge does), and what it reports comes straight back.
 * `hold()` keeps the target's answers (a slow network) until `flush()`.
 */
class FakeLink implements LinkLike {
  view: LinkView = { connected: true, targets: [], queue: null, error: null };
  sent: RemoteCommand[] = [];
  private listeners = new Set<() => void>();
  private held = false;
  private revision = 0;
  private signature = "";

  constructor(readonly engine: PlayerEngine) {
    engine.subscribe(() => !this.held && this.report());
    this.report();
  }

  acquire = () => () => undefined;
  watch = () => undefined;
  getView = () => this.view;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  send = (_target: string, command: RemoteCommand) => {
    this.sent.push(command);
    applyCommand(this.engine, command, (speed) => this.engine.setSpokenSpeed(speed));
  };

  hold(): void {
    this.held = true;
  }

  flush(): void {
    this.held = false;
    this.report();
  }

  private report(): void {
    const snapshot = this.engine.getSnapshot();
    const signature = snapshot.keys.join(",");
    if (signature !== this.signature) this.revision += 1;
    this.signature = signature;
    const state = remoteStateOf(snapshot, this.engine, this.revision);
    this.view = {
      ...this.view,
      queue: { revision: this.revision, keys: snapshot.keys, tracks: snapshot.queue },
      targets: [{ id: TARGET, playerName: "PC", device: "Edge", kind: "browser", state, at: Date.now() }],
    };
    this.listeners.forEach((listener) => listener());
  }
}

function setup() {
  const engine = new PlayerEngine({ streamUrl: (id) => `/stream/${id}`, createAudio: () => new FakeAudio() });
  const link = new FakeLink(engine);
  const remote = new RemoteController(link);
  remote.connect(TARGET);
  const ids = () => remote.getSnapshot().queue.map((t) => t.id);
  return { engine, link, remote, ids };
}

describe("RemoteController", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("mirrors the target's queue and track", () => {
    const { engine, remote, ids } = setup();
    engine.playQueue(tracks, 1);
    const snapshot = remote.getSnapshot();
    expect(ids()).toEqual(["a", "b", "c", "d"]);
    expect(snapshot.current?.id).toBe("b");
    expect(snapshot.index).toBe(1);
    expect(snapshot.playing).toBe(true);
    expect(snapshot.keys).toEqual(engine.getSnapshot().keys);
  });

  it("plays and queues on the target", () => {
    const { engine, remote, ids } = setup();
    remote.playQueue(tracks.slice(0, 2), 1);
    expect(engine.getSnapshot().current?.id).toBe("b");
    remote.add([tracks[3] as Track]);
    remote.playNext([tracks[2] as Track]);
    expect(engine.getSnapshot().queue.map((t) => t.id)).toEqual(["a", "b", "c", "d"]);
    expect(ids()).toEqual(["a", "b", "c", "d"]);
    remote.playAt(3);
    expect(engine.getSnapshot().current?.id).toBe("d");
  });

  it("edits the queue by key, at once here", () => {
    const { engine, link, remote, ids } = setup();
    engine.playQueue(tracks, 0);
    link.hold(); // the target's answer comes later
    remote.move(3, 1); // drag "d" after "a"
    expect(ids()).toEqual(["a", "d", "b", "c"]); // shown moved before the answer
    expect(remote.getSnapshot().current?.id).toBe("a");
    link.flush();
    expect(engine.getSnapshot().queue.map((t) => t.id)).toEqual(["a", "d", "b", "c"]);
    expect(ids()).toEqual(["a", "d", "b", "c"]);

    remote.move(0, 3); // the current one, to the end
    expect(engine.getSnapshot().queue.map((t) => t.id)).toEqual(["d", "b", "c", "a"]);
    expect(remote.getSnapshot().index).toBe(3); // still the current one, where it went

    remote.remove([1, 2]);
    expect(engine.getSnapshot().queue.map((t) => t.id)).toEqual(["d", "a"]);
    remote.undo();
    expect(engine.getSnapshot().queue.map((t) => t.id)).toEqual(["d", "b", "c", "a"]);
  });

  it("names entries by key: a queue changed meanwhile is not edited by position", () => {
    const { engine, link, remote } = setup();
    engine.playQueue(tracks, 0);
    link.hold();
    engine.remove([0]); // on the target: "a" removed; the remote still shows it
    remote.remove([0]); // the remote removes "a" too: nothing else goes
    link.flush();
    expect(engine.getSnapshot().queue.map((t) => t.id)).toEqual(["b", "c", "d"]);
  });

  it("advances the position while the target plays, and seeks at once", () => {
    const { engine, link, remote } = setup();
    engine.playQueue(tracks, 0);
    vi.advanceTimersByTime(2000);
    expect(remote.getSnapshot().position).toBeCloseTo(2, 0);
    link.hold();
    remote.seek(100);
    expect(remote.getSnapshot().position).toBe(100);
    expect(link.sent.at(-1)).toEqual({ name: "seek", position: 100 });
  });

  it("stops mirroring when disconnected", () => {
    const { engine, remote } = setup();
    engine.playQueue(tracks, 0);
    remote.connect(null);
    expect(remote.getSnapshot().queue).toEqual([]);
    expect(remote.getSnapshot().current).toBeNull();
  });
});
