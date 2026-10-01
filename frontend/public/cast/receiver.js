// The server player's Now playing screen on a TV (see receiver.html). Plain JavaScript:
// this page is served as is (no build), to Chromecasts.
//
// What the TV plays is behind the server player: the sound it plays now was sent a few
// seconds ago. The server keeps a timeline of what played when, on the stream's own clock
// (seconds of sound sent), and where this listener's sound started on that clock (the
// stream URL is given a `listener` name for that). So: heard = start + seconds played here,
// and what played at `heard` is the last change of the timeline before it.
//
// receiver.html?stream=<the stream's URL> plays it here, with the TV's screen. A preview in
// any browser (a click starts the sound); with `&autoplay=1`, the screen opened for a TV by
// the web UI: DashCast (a published receiver that opens a page) on the Chromecast itself,
// or Chrome mirroring it from the computer (Presentation API).
//
// Chromecasts have little power: the screen is checked 10 times a second (not at every
// frame), and only what changed is written to the page.

(function () {
  "use strict";

  const POLL_MS = 1000;
  const TICK_MS = 100;
  const STREAM = /^(https?:\/\/[^?#]+?)\/api\/stream\/([A-Za-z0-9_-]+)/;
  const params = new URLSearchParams(location.search);
  const preview = params.get("stream");
  const el = {};
  for (const id of ["audio", "backdrop", "idle", "screen", "cover", "paused", "title", "artist", "elapsed", "bar", "duration", "lyrics", "lines"]) {
    el[id] = document.getElementById(id);
  }
  const audio = el.audio;

  let stream = null; // { base, key, listener }
  let now = null; // the last /now answer
  let shownKey; // the entry shown (its key), to update what changes with it
  let lyrics = null; // { lines, items, centers }: synced lyrics only (centers: measure())
  let lyricsFor = null;
  let lastLine = -2;
  const written = {}; // what is on the page, not to write it again

  /** Sets a text or an attribute only when it changed (writing costs, even the same). */
  function set(key, value, apply) {
    if (written[key] === value) return;
    written[key] = value;
    apply(value);
  }

  /** A server player's stream to follow: where it is, and this listener's name on it. */
  function follow(url) {
    const match = STREAM.exec(url || "");
    if (!match) return null;
    const listener = Math.random().toString(36).slice(2, 12);
    stream = { base: match[1], key: match[2], listener };
    shownKey = undefined;
    lyrics = null;
    lyricsFor = null;
    return `${match[1]}/api/stream/${match[2]}?listener=${listener}`;
  }

  if (!preview) {
    el.idle.textContent = "Open it from Sound-Barrier: the server player's Cast menu";
  } else {
    const named = follow(preview);
    el.idle.textContent = named ? "Sound-Barrier" : "Not a Sound-Barrier stream URL";
    if (named) {
      audio.src = named;
      // A TV plays at once; a browser may want a click first.
      const clickToListen = () => {
        el.idle.textContent = "Click to listen";
        document.body.addEventListener("click", () => void audio.play(), { once: true });
      };
      if (params.get("autoplay") === "1") audio.play().catch(clickToListen);
      else clickToListen();
    }
  }

  // --- following the server player ------------------------------------------------------

  async function poll() {
    if (stream) {
      try {
        const url = `${stream.base}/api/stream/${stream.key}/now?listener=${stream.listener}`;
        const response = await fetch(url, { cache: "no-store" });
        if (response.ok) now = await response.json();
      } catch (e) {
        // the server for a moment out of reach: the next poll
      }
    }
    setTimeout(poll, POLL_MS);
  }
  poll();

  /** What plays here now: the timeline's change for the stream time heard, advanced. */
  function heard() {
    if (!now || !now.timeline || !now.timeline.length) return null;
    // Before this listener is known (its first second): the server's time, a bit ahead.
    const at =
      now.listenerStart === null || now.listenerStart === undefined
        ? now.streamTime
        : now.listenerStart + audio.currentTime;
    let mark = now.timeline[0];
    for (const change of now.timeline) if (change.at <= at) mark = change;
    const elapsed = mark.playing ? Math.max(at - mark.at, 0) * mark.rate : 0;
    return { mark, position: mark.position + elapsed };
  }

  // --- drawing --------------------------------------------------------------------------

  function time(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const rest = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${rest}` : `${m}:${rest}`;
  }

  function coverUrl(track, size) {
    if (!stream || !track || !track.coverArt) return "";
    return `${stream.base}/api/stream/${stream.key}/cover?id=${encodeURIComponent(track.coverArt)}&size=${size}`;
  }

  /** The chapter playing inside an audiobook's file, if it has some, and where it ends. */
  function chapterAt(track, position, duration) {
    let found = null;
    let end = duration;
    for (const chapter of track.chapters || []) {
      if (chapter.start <= position + 0.5) found = chapter;
      else if (found) {
        end = chapter.start;
        break;
      }
    }
    return found && { title: found.title, start: found.start, end: Math.max(end, found.start) };
  }

  async function loadLyrics(track) {
    lyricsFor = track.id;
    lyrics = null;
    lastLine = -2;
    el.lyrics.hidden = true;
    try {
      const url = `${stream.base}/api/stream/${stream.key}/lyrics?song=${encodeURIComponent(track.id)}`;
      const response = await fetch(url);
      const found = response.ok ? await response.json() : null;
      // Synced lyrics only: a TV cannot scroll, the first lines of the others are no use.
      if (lyricsFor !== track.id || !found || !found.found || !found.synced || !found.lines.length) return;
      const items = found.lines.map((line) => {
        const item = document.createElement("li");
        item.textContent = line.text || "♪";
        return item;
      });
      el.lines.replaceChildren(...items);
      el.lyrics.hidden = false;
      lyrics = { lines: found.lines, items, centers: measure(items) };
      drawLyrics(0, true);
    } catch (e) {
      // no lyrics then
    }
  }

  /** Where each line's middle is in the list: measured once, not at every change of line. */
  function measure(items) {
    return items.map((item) => item.offsetTop + item.offsetHeight / 2);
  }

  // The text scales with the window (vw): resized (a browser window), the lines wrap anew.
  // Once a frame at most while the window is dragged.
  let lastPosition = 0;
  let resizeFrame = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      if (!lyrics) return;
      lyrics.centers = measure(lyrics.items);
      drawLyrics(lastPosition, true);
    });
  });

  /** The line playing (synced lyrics), kept in the middle; its neighbours less faded. */
  function drawLyrics(position, force) {
    lastPosition = position;
    if (!lyrics) return;
    let current = -1;
    const ms = position * 1000;
    const lines = lyrics.lines;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].startMs !== null && lines[i].startMs <= ms) current = i;
      else if (lines[i].startMs !== null && lines[i].startMs > ms) break;
    }
    if (current === lastLine && !force) return;
    const previous = lastLine;
    lastLine = current;
    // Only the lines whose look changes: around the old current one and the new one.
    const touched = new Set();
    for (const center of [previous, current]) for (let d = -2; d <= 2; d++) touched.add(center + d);
    for (const i of touched) {
      const item = lyrics.items[i];
      if (!item) continue;
      const distance = Math.abs(i - current);
      item.className = current < 0 ? "" : distance === 0 ? "current" : distance === 1 ? "near1" : distance === 2 ? "near2" : "";
    }
    const offset = lyrics.centers[Math.max(current, 0)] || 0;
    el.lines.style.transform = `translate3d(0, ${-offset}px, 0)`;
  }

  function draw() {
    const state = heard();
    const track = state && state.mark.track;
    set("idle", Boolean(track), (shown) => {
      el.idle.hidden = shown;
      el.screen.hidden = !shown;
      el.backdrop.hidden = !shown;
    });
    if (!track) return;
    if (state.mark.key !== shownKey) {
      shownKey = state.mark.key;
      set("cover", coverUrl(track, 800), (url) => (el.cover.src = url || ""));
      // Tiny, stretched: blurred by the scaling itself.
      set("backdrop", coverUrl(track, 32), (url) => (el.backdrop.src = url || ""));
      set("title", track.title, (text) => (el.title.textContent = text));
      if (lyricsFor !== track.id) void loadLyrics(track);
    }
    const duration = track.durationSeconds || 0;
    const position = duration ? Math.min(state.position, duration) : state.position;
    const chapter = chapterAt(track, position, duration);
    const artist = [chapter && chapter.title, track.artist, track.album !== track.title && track.album].filter(Boolean).join(" · ");
    set("artist", artist, (text) => (el.artist.textContent = text));
    set("paused", state.mark.playing, (playing) => (el.paused.hidden = playing));
    // The chapter playing when the file has chapters inside it (as the web UI's bar).
    const start = chapter ? chapter.start : 0;
    const length = chapter ? chapter.end - chapter.start : duration;
    set("elapsed", time(Math.max(position - start, 0)), (text) => (el.elapsed.textContent = text));
    set("durationText", time(length), (text) => (el.duration.textContent = text));
    const ratio = length > 0 ? Math.min(1, Math.max(position - start, 0) / length) : 0;
    set("bar", Math.round(ratio * 500) / 500, (value) => (el.bar.style.transform = `scaleX(${value})`));
    drawLyrics(position, false);
  }
  setInterval(draw, TICK_MS);
})();
