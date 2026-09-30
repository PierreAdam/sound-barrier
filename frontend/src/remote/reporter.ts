// A controllable player's reports to its remotes: its queue when its entries change (not
// their metadata: a key is one track), its state when it changes, when its position jumps
// (a seek), and every few seconds while playing (the remotes' clocks). Used by a tab made
// controllable (RemoteTargetBridge) and by the TV page (cast/tv).

import type { PlayerEngine } from "../player/engine";
import { remoteStateOf } from "./apply";
import type { RemoteQueue, RemoteState } from "./protocol";

export const HEARTBEAT_MS = 10_000;
// The position is sent again when it moved this far from where remotes expect it (a seek).
const JUMP_SECONDS = 1.5;

export interface Reports {
  queue(queue: RemoteQueue): void;
  state(state: RemoteState): void;
}

export interface Reporter {
  /** Sends what changed; `force`: the state and the queue anyway (a new connection). */
  report(force?: boolean): void;
  /** Reports on each change of the engine, and while playing: returns the stop. */
  follow(): () => void;
}

export function createReporter(engine: PlayerEngine, send: Reports, ready: () => boolean = () => true): Reporter {
  let sent: { signature: string; position: number; at: number; playing: boolean; rate: number } | null = null;
  let queueSignature = "";
  let queueRevision = 0;

  const sendQueue = (force: boolean) => {
    const { keys, queue } = engine.getSnapshot();
    const signature = keys.join(",");
    if (!force && signature === queueSignature) return;
    if (signature !== queueSignature) queueRevision += 1;
    queueSignature = signature;
    send.queue({ revision: queueRevision, keys, tracks: queue });
  };

  const report = (force = false) => {
    if (!ready()) return;
    sendQueue(force); // first: the state names the queue it goes with
    const state = remoteStateOf(engine.getSnapshot(), engine, queueRevision);
    const signature = JSON.stringify({ ...state, position: 0, rate: 0 });
    const now = Date.now();
    const expected = sent ? sent.position + (sent.playing ? ((now - sent.at) / 1000) * sent.rate : 0) : state.position;
    const jumped = Math.abs(state.position - expected) > JUMP_SECONDS;
    if (!force && sent && signature === sent.signature && !jumped) return;
    sent = { signature, position: state.position, at: now, playing: state.playing, rate: state.rate };
    send.state(state);
  };

  const follow = () => {
    const unsubscribe = engine.subscribe(() => report());
    const heartbeat = setInterval(() => {
      if (engine.getSnapshot().playing) report(true);
    }, HEARTBEAT_MS);
    return () => {
      clearInterval(heartbeat);
      unsubscribe();
    };
  };

  return { report, follow };
}
