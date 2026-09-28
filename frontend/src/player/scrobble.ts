// When a play counts (the usual scrobbling rule): the track lasts at least 30 s and was
// heard for half its length, or 4 minutes for long tracks.
const MIN_TRACK_SECONDS = 30;
const MAX_WAIT_SECONDS = 240;
/** Back under this position after having counted: the track is played again (repeat). */
const RESTART_SECONDS = 2;

export interface ScrobbleEvents {
  nowPlaying(trackId: string): void;
  played(trackId: string, startedAt: number): void;
}

/**
 * Follows the player and reports each play once: "now playing" when a track starts,
 * "played" when enough of it was heard. Feed it every player update.
 */
export function createScrobbler(events: ScrobbleEvents, now: () => number = Date.now) {
  let key: number | null = null;
  let started = false;
  let counted = false;
  let startedAt = 0;

  return (update: { key: number | null; trackId: string | null; playing: boolean; position: number; duration: number }) => {
    if (update.key !== key) {
      key = update.key;
      started = counted = false;
    } else if (counted && update.position < RESTART_SECONDS) {
      started = counted = false; // the same entry again (repeat one)
    }
    if (update.trackId === null || !update.playing) return;
    if (!started) {
      started = true;
      startedAt = now();
      events.nowPlaying(update.trackId);
    }
    const duration = update.duration;
    if (!counted && duration >= MIN_TRACK_SECONDS && update.position >= Math.min(duration / 2, MAX_WAIT_SECONDS)) {
      counted = true;
      events.played(update.trackId, startedAt);
    }
  };
}
