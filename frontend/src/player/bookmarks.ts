// Audiobooks and podcasts ("long-form" tracks): where the user stops is kept as a Subsonic
// bookmark, and playing the track again resumes there. Music is never bookmarked.
//
// Pure logic, fed with the player's snapshots (see useBookmarks in PlayerContext.tsx).

import type { PlayerSnapshot, Track } from "./engine";

export const SAVE_EVERY_S = 15; // while playing
export const FINISHED_S = 30; // stopped this close to the end: listened, the bookmark goes
export const RESUME_FROM_S = 5; // a bookmark before that is not worth resuming
export const STARTED_S = 3; // a track "starts" below this position (else it was restored)

export interface BookmarkActions {
  save(track: Track, positionSeconds: number, keepalive?: boolean): void;
  remove(track: Track, keepalive?: boolean): void;
  /** A long-form track just started from its beginning: resume it if it has a bookmark. */
  resume(track: Track): void;
  /** A long-form track became the current one (however it started): before `resume`. */
  started?(track: Track): void;
}

interface Playing {
  key: number | null;
  track: Track | null;
  position: number;
  duration: number;
  playing: boolean;
  savedAt: number; // position of the last save
}

/** Follows the snapshots and calls `actions` when a bookmark must change. */
export function createBookmarkKeeper(actions: BookmarkActions) {
  let last: Playing = { key: null, track: null, position: 0, duration: 0, playing: false, savedAt: -1 };

  function persist(from: Playing, keepalive = false): void {
    const track = from.track;
    if (!track?.longForm) return;
    const duration = from.duration || track.durationSeconds || 0;
    if (duration && from.position >= duration - FINISHED_S) actions.remove(track, keepalive);
    else if (from.position >= RESUME_FROM_S) actions.save(track, from.position, keepalive);
  }

  return {
    update(state: PlayerSnapshot): void {
      const key = state.index >= 0 ? (state.keys[state.index] ?? null) : null;
      const track = state.current;
      if (key !== last.key) {
        persist(last); // the previous track: where it was left (or finished)
        last = { key, track, position: state.position, duration: state.duration, playing: state.playing, savedAt: -1 };
        if (track?.longForm) actions.started?.(track);
        // Not when it was started at a chosen place (a chapter).
        if (track?.longForm && state.position < STARTED_S && !state.positioned) actions.resume(track);
        return;
      }
      const wasPlaying = last.playing;
      last = { ...last, track, position: state.position, duration: state.duration, playing: state.playing };
      if (!track?.longForm) return;
      if (wasPlaying && !state.playing) {
        persist(last); // paused, or stopped at the end of the queue
        last.savedAt = state.position;
      } else if (state.playing && Math.abs(state.position - last.savedAt) >= SAVE_EVERY_S) {
        persist(last);
        last.savedAt = state.position;
      }
    },
    /** The page is closing: save where the current track is. */
    leave(): void {
      persist(last, true);
    },
    /** The player is moved to where another device left it: what it had is not saved. */
    forget(): void {
      last = { key: null, track: null, position: 0, duration: 0, playing: false, savedAt: -1 };
    },
  };
}
