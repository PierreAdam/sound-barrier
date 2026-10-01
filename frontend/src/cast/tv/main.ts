// The TV page (tv.html): this browser's player on a TV. It plays with its own player
// engine what the tab that opened it asks (in remote mode: the same commands as a tab made
// controllable), reports its state and queue back, keeps scrobbles and bookmarks like any
// player, and shows Now playing. The music comes from the server as usual (the Subsonic
// credentials of the tab that opened it); nothing goes anywhere else.

import { coverVersion } from "../../api/coverVersions";
import { SubsonicClient } from "../../api/subsonic";
import { createBookmarkKeeper, FINISHED_S, RESUME_FROM_S, STARTED_S } from "../../player/bookmarks";
import { type AudioLike, PlayerEngine, type Track } from "../../player/engine";
import { progressOf } from "../../player/progress";
import { createScrobbler } from "../../player/scrobble";
import { applyCommand } from "../../remote/apply";
import { createReporter } from "../../remote/reporter";
import { type ControllerChannel, connectToController } from "./channel";

const TICK_MS = 100;

const el = Object.fromEntries(
  ["backdrop", "idle", "screen", "cover", "paused", "title", "artist", "elapsed", "bar", "duration", "lyrics", "lines"].map(
    (id) => [id, document.getElementById(id) as HTMLElement],
  ),
) as Record<string, HTMLElement>;

function idle(text: string): void {
  el.idle!.textContent = text;
  el.idle!.hidden = false;
  el.screen!.hidden = true;
  el.backdrop!.hidden = true;
}

void connectToController().then((channel) => {
  if (!channel) {
    idle("Open it from Sound-Barrier: Player menu → Cast this player");
    return;
  }
  let player: { stop(): void } | null = null;
  channel.onMessage((message) => {
    if (message.type === "hello" && !player) {
      player = play(channel, new SubsonicClient(message.credentials));
    } else if (message.type === "bye") {
      // The computer plays again: silent here first (a window may not close, e.g. embedded).
      player?.stop();
      idle("Playing on the computer again");
      channel.close();
    }
  });
  channel.send({ type: "ready" });
});

function play(channel: ControllerChannel, client: SubsonicClient): { stop(): void } {
  let blocked = false;
  // The browser may refuse to start the sound before a click here (a window): said to the
  // tab driving this page, and a click here starts it.
  const createAudio = (): AudioLike => {
    const audio = new Audio();
    const start = audio.play.bind(audio);
    audio.play = () =>
      start().catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "NotAllowedError" && !blocked) {
          blocked = true;
          channel.send({ type: "blocked" });
          idle("Click here to start the sound");
          document.body.addEventListener(
            "click",
            () => {
              blocked = false;
              engine.togglePlay();
            },
            { once: true },
          );
        }
        throw e;
      });
    return audio;
  };
  const engine = new PlayerEngine({ streamUrl: (id) => client.url("stream", { id }), createAudio, storage: null });

  // Reported to the tab driving it, and its commands applied (as a controllable tab).
  channel.onMessage((message) => {
    if (message.type === "command") applyCommand(engine, message.command, (speed) => engine.setSpokenSpeed(speed));
  });
  const reporter = createReporter(engine, {
    queue: (queue) => channel.send({ type: "queue", queue }),
    state: (state) => channel.send({ type: "state", state }),
  });
  const stopReporting = reporter.follow();
  reporter.report(true);

  // Plays and bookmarks, as the web UI's own player keeps them.
  const scrobble = createScrobbler({
    nowPlaying: (id) => void client.call("scrobble", { id, submission: "false" }).catch(() => undefined),
    played: (id, startedAt) =>
      void client.call("scrobble", { id, submission: "true", time: String(startedAt) }).catch(() => undefined),
  });
  const bookmarks = createBookmarkKeeper({
    save: (track, seconds, keepalive) =>
      void client
        .call("createBookmark", { id: track.id, position: String(Math.round(seconds * 1000)) }, { keepalive })
        .catch(() => undefined),
    remove: (track, keepalive) => void client.call("deleteBookmark", { id: track.id }, { keepalive }).catch(() => undefined),
    resume: (track) =>
      void client
        .call("getSong", { id: track.id })
        .then(({ song }) => {
          const seconds = (song.bookmarkPosition ?? 0) / 1000;
          const duration = song.duration ?? track.durationSeconds ?? 0;
          if (engine.getSnapshot().current?.id !== track.id || engine.currentTime >= STARTED_S) return;
          if (seconds < RESUME_FROM_S || (duration && seconds >= duration - FINISHED_S)) return;
          engine.seek(seconds);
        })
        .catch(() => undefined),
  });
  engine.subscribe(() => {
    const state = engine.getSnapshot();
    scrobble({
      key: state.index >= 0 ? (state.keys[state.index] ?? null) : null,
      trackId: state.current?.id ?? null,
      playing: state.playing,
      position: state.position,
      duration: state.duration,
    });
    bookmarks.update(state);
  });
  window.addEventListener("pagehide", () => bookmarks.leave());

  const screen = new Screen(client);
  const drawing = setInterval(() => screen.draw(engine), TICK_MS);
  return {
    stop: () => {
      stopReporting();
      clearInterval(drawing);
      bookmarks.leave();
      engine.destroy();
    },
  };
}

// --- the screen -------------------------------------------------------------------------

function time(seconds: number | undefined): string {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${rest}` : `${m}:${rest}`;
}

interface Lyrics {
  songId: string;
  starts: number[]; // ms, per line
  items: HTMLElement[];
  centers: number[]; // px, where each line is in the list (measured again when resized)
}

/** Where each line's middle is in the list: measured once, not at every change of line. */
function measure(items: HTMLElement[]): number[] {
  return items.map((item) => item.offsetTop + item.offsetHeight / 2);
}

/** Now playing, as the server player's receiver shows it (writes only what changed). */
class Screen {
  private written = new Map<string, unknown>();
  private shownKey: number | null | undefined;
  private lyrics: Lyrics | null = null;
  private lyricsFor: string | null = null;
  private lastLine = -2;

  constructor(private readonly client: SubsonicClient) {
    // The text scales with the window (vw): resized (a TV window), the lines wrap anew.
    // Once a frame at most while the window is dragged (a transcript has many lines).
    let frame = 0;
    window.addEventListener("resize", () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!this.lyrics) return;
        this.lyrics.centers = measure(this.lyrics.items);
        this.drawLyrics(this.lastPosition, true);
      });
    });
  }

  private lastPosition = 0;

  private set<T>(key: string, value: T, apply: (value: T) => void): void {
    if (this.written.get(key) === value) return;
    this.written.set(key, value);
    apply(value);
  }

  private cover(track: Track, size: number): string {
    return track.coverArt
      ? this.client.url("getCoverArt", { id: track.coverArt, size, ...coverVersion(track.coverArt) })
      : "";
  }

  draw(engine: PlayerEngine): void {
    const state = engine.getSnapshot();
    const track = state.current;
    this.set("shown", Boolean(track), (shown) => {
      el.idle!.hidden = shown;
      el.screen!.hidden = !shown;
      el.backdrop!.hidden = !shown;
      if (!shown) el.idle!.textContent = "Sound-Barrier";
    });
    if (!track) return;
    const key = state.keys[state.index] ?? null;
    if (key !== this.shownKey) {
      this.shownKey = key;
      this.set("cover", this.cover(track, 800), (url) => ((el.cover as HTMLImageElement).src = url));
      // Tiny, stretched: blurred by the scaling itself.
      this.set("backdrop", this.cover(track, 32), (url) => ((el.backdrop as HTMLImageElement).src = url));
      this.set("title", track.title, (text) => (el.title!.textContent = text));
      if (this.lyricsFor !== track.id) void this.loadLyrics(track);
    }
    const position = engine.currentTime;
    const duration = state.duration;
    const chapter = track.chapters?.[state.chapter];
    const artist = [chapter?.title, track.artist, track.album !== track.title && track.album].filter(Boolean).join(" · ");
    this.set("artist", artist, (text) => (el.artist!.textContent = text));
    this.set("paused", state.playing, (playing) => (el.paused!.hidden = playing));
    // The chapter playing when the file has chapters inside it (see player/progress.ts).
    const span = progressOf(track, position, duration, state.chapter);
    const length = span.end - span.start;
    this.set("elapsed", time(Math.max(position - span.start, 0)), (text) => (el.elapsed!.textContent = text));
    this.set("duration", time(length), (text) => (el.duration!.textContent = text));
    const ratio = length > 0 ? Math.min(1, Math.max(position - span.start, 0) / length) : 0;
    this.set("bar", Math.round(ratio * 500) / 500, (value) => (el.bar!.style.transform = `scaleX(${value})`));
    this.drawLyrics(position);
  }

  /** Synced lyrics only: a TV cannot scroll, the first lines of the others are no use. */
  private async loadLyrics(track: Track): Promise<void> {
    this.lyricsFor = track.id;
    this.lyrics = null;
    this.lastLine = -2;
    el.lyrics!.hidden = true;
    try {
      const { lyricsList } = await this.client.call("getLyricsBySongId", { id: track.id });
      const synced = lyricsList.structuredLyrics?.find((l) => l.synced && l.line?.length);
      if (this.lyricsFor !== track.id || !synced?.line) return;
      const lines = synced.line;
      const items = lines.map((line) => {
        const item = document.createElement("li");
        item.textContent = line.value || "♪";
        return item;
      });
      el.lines!.replaceChildren(...items);
      el.lyrics!.hidden = false;
      this.lyrics = { songId: track.id, starts: lines.map((l) => l.start ?? Infinity), items, centers: measure(items) };
      this.drawLyrics(0, true);
    } catch {
      // no lyrics then
    }
  }

  /** The line playing, kept in the middle; its neighbours less faded. */
  private drawLyrics(position: number, force = false): void {
    this.lastPosition = position;
    const lyrics = this.lyrics;
    if (!lyrics) return;
    const ms = position * 1000;
    let current = -1;
    for (let i = 0; i < lyrics.starts.length && (lyrics.starts[i] ?? Infinity) <= ms; i++) current = i;
    if (current === this.lastLine && !force) return;
    const previous = this.lastLine;
    this.lastLine = current;
    // Only the lines whose look changes: around the old current one and the new one.
    for (const center of [previous, current]) {
      for (let i = center - 2; i <= center + 2; i++) {
        const item = lyrics.items[i];
        if (!item) continue;
        const distance = Math.abs(i - current);
        item.className =
          current < 0 ? "" : distance === 0 ? "current" : distance === 1 ? "near1" : distance === 2 ? "near2" : "";
      }
    }
    const offset = lyrics.centers[Math.max(current, 0)] ?? 0;
    el.lines!.style.transform = `translate3d(0, ${-offset}px, 0)`;
  }
}
