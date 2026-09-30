// A controllable tab (RemoteTargetBridge): what it reports of its player, and how it
// applies a remote's commands (as its own controls would; the values are checked here).

import { SPEEDS } from "../components/PlayerBar";
import type { PlayerEngine, PlayerSnapshot } from "../player/engine";
import { type RemoteCommand, type RemoteState, tracksFrom } from "./protocol";

export function remoteStateOf(snapshot: PlayerSnapshot, engine: PlayerEngine, queueRevision: number): RemoteState {
  const { queue: _queue, keys, ...rest } = snapshot;
  const currentKey = keys[snapshot.index] ?? null;
  return { ...rest, rate: engine.playbackRate, queueRevision, currentKey };
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

/** The positions of these entries in the queue (keys no longer queued are left out). */
function positionsOf(snapshot: PlayerSnapshot, keys: number[]): number[] {
  return keys.map((key) => snapshot.keys.indexOf(key)).filter((position) => position >= 0);
}

/** Applies a remote's command to this tab's player, as its own controls would. */
export function applyCommand(engine: PlayerEngine, command: RemoteCommand, setSpeed: (speed: number) => void): void {
  const state = engine.getSnapshot();
  const end = Math.max(state.duration - 0.5, 0);
  switch (command.name) {
    case "toggle":
      engine.togglePlay();
      break;
    case "play":
      if (!state.playing) engine.togglePlay();
      break;
    case "pause":
      engine.pause();
      break;
    case "previous":
      engine.previous();
      break;
    case "next":
      engine.next();
      break;
    case "seek":
      if (Number.isFinite(command.position)) engine.seek(clamp(command.position, 0, end));
      break;
    case "skip":
      if (Number.isFinite(command.seconds)) engine.seek(clamp(engine.currentTime + command.seconds, 0, end));
      break;
    case "volume":
      if (Number.isFinite(command.value)) engine.setVolume(clamp(command.value, 0, 1));
      break;
    case "mute":
      engine.toggleMute();
      break;
    // As on the player bar: not for audiobooks and podcasts...
    case "shuffle":
      if (!state.spoken) engine.toggleShuffle();
      break;
    case "repeat":
      if (!state.spoken) engine.cycleRepeat();
      break;
    case "crossfade":
      if (!state.spoken) engine.toggleCrossfade();
      break;
    case "crossfadeSeconds":
      if (Number.isFinite(command.value)) engine.setCrossfadeSeconds(command.value);
      break;
    // ...and only for them.
    case "pauseAtEnd":
      if (state.spoken) engine.setPauseAtEnd(command.value ?? !state.pauseAtEnd);
      break;
    case "speed":
      if (SPEEDS.includes(command.value)) setSpeed(command.value);
      break;
    // The queue: entries named by key.
    case "playQueue": {
      const tracks = tracksFrom(command.tracks);
      if (!tracks.length) break;
      const index = Number.isInteger(command.index) ? clamp(command.index, 0, tracks.length - 1) : 0;
      const startAt = Number.isFinite(command.startAt) ? command.startAt : undefined;
      engine.playQueue(tracks, index, startAt);
      break;
    }
    case "add":
      engine.add(tracksFrom(command.tracks));
      break;
    case "playNext":
      engine.playNext(tracksFrom(command.tracks));
      break;
    case "playAt": {
      const [position] = positionsOf(state, [command.key]);
      if (position !== undefined) engine.playAt(position);
      break;
    }
    case "remove":
      if (Array.isArray(command.keys)) engine.remove(positionsOf(state, command.keys));
      break;
    case "move": {
      const from = state.keys.indexOf(command.key);
      if (from < 0) break;
      const others = state.keys.filter((key) => key !== command.key);
      const to = command.before === null ? others.length : others.indexOf(command.before);
      if (to >= 0) engine.move(from, to);
      break;
    }
    case "clear":
      engine.clear();
      break;
    case "undo":
      engine.undo();
      break;
  }
}
