// Sound-Barrier's Google Cast receiver (see receiver.html). Plain JavaScript: this page is
// served as is (no build), to Chromecasts.
//
// What the TV plays is behind the server player: the sound it plays now was sent a few
// seconds ago. The server keeps a timeline of what played when, on the stream's own clock
// (seconds of sound sent), and where this listener's sound started on that clock (the
// stream URL is given a `listener` name for that). So: heard = start + seconds played here,
// and what played at `heard` is the last change of the timeline before it.
//
// Without the Cast framework: receiver.html?stream=<the stream's URL> plays it here, with
// the TV's screen. A preview in any browser (a click starts the sound); with `&autoplay=1`,
// the screen opened for a TV by the web UI when no receiver of our own is registered:
// DashCast (a published receiver that opens a page) on the Chromecast itself, or Chrome
// mirroring it from the computer (Presentation API).
//
// Chromecasts have little power: the screen is checked 10 times a second (not at every
// frame), and only what changed is written to the page.

(function () {
  "use strict";

  const POLL_MS = 1000;
  const TICK_MS = 100;
  const CAF = "https://www.gstatic.com/cast/sdk/libs/caf_receiver/v3/cast_receiver_framework.js";
  const STREAM = /^(https?:\/\/[^?#]+?)\/api\/stream\/([A-Za-z0-9_-]+)/;
  const params = new URLSearchParams(location.search);
  const preview = params.get("stream");
  const el = {};
  for (const id of ["audio", "backdrop", "idle", "screen", "cover", "paused", "title", "artist", "elapsed", "bar", "duration", "lyrics", "lines"]) {
    el[id] = document.getElementById(id);
  }
  const audio = el.audio;

  let player = null; // the Cast framework's, when this page is our Cast app
  let stream = null; // { base, key, listener }
  let now = null; // the last /now answer
  let shownKey; // the entry shown (its key), to update what changes with it
  let lyrics = null; // { lines, items, centers }: synced lyrics only
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

  /** Our Cast app: the framework plays what the sender asks (loaded only then: it is big). */
  function startReceiver() {
    const script = document.createElement("script");
    script.src = CAF;
    script.onload = () => {
      const context = cast.framework.CastReceiverContext.getInstance();
      player = context.getPlayerManager();
      player.setMediaElement(audio);
      // Asked to play a server player's stream: remember where it is, name this listener.
      player.setMessageInterceptor(cast.framework.messages.MessageType.LOAD, (request) => {
        const named = follow(request.media.contentUrl || request.media.contentId);
        if (named) {
          request.media.contentUrl = named;
          request.media.contentId = named;
        }
        request.media.streamType = cast.framework.messages.StreamType.LIVE;
        return request;
      });
      const options = new cast.framework.CastReceiverOptions();
      // Paused, the server player sends silence: still playing here, nothing to time out.
      options.disableIdleTimeout = true;
      options.maxInactivity = 3600;
      context.start(options);
    };
    document.head.appendChild(script);
  }

  if (!preview) {
    startReceiver();
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

  /** The chapter playing inside an audiobook's file, if it has some. */
  function chapterAt(track, position) {
    let found = null;
    for (const chapter of track.chapters || []) if (chapter.start <= position + 0.5) found = chapter;
    return found;
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
      // Where each line is in the list: measured once, not at every change of line.
      el.lines.replaceChildren(...items);
      el.lyrics.hidden = false;
      const centers = items.map((item) => item.offsetTop + item.offsetHeight / 2);
      lyrics = { lines: found.lines, items, centers };
      drawLyrics(0, true);
    } catch (e) {
      // no lyrics then
    }
  }

  /** The line playing (synced lyrics), kept in the middle; its neighbours less faded. */
  function drawLyrics(position, force) {
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

  /** The TV's own media information (Google Home, phones' notifications): the track. */
  function announce(track) {
    if (!player) return;
    const info = player.getMediaInformation();
    if (!info) return;
    const metadata = new cast.framework.messages.MusicTrackMediaMetadata();
    metadata.title = track.title;
    metadata.artist = track.artist || "";
    metadata.albumName = track.album || "";
    const cover = coverUrl(track, 512);
    metadata.images = cover ? [new cast.framework.messages.Image(cover)] : [];
    info.metadata = metadata;
    player.setMediaInformation(info, true);
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
      set("durationText", time(track.durationSeconds), (text) => (el.duration.textContent = text));
      announce(track);
      if (lyricsFor !== track.id) void loadLyrics(track);
    }
    const duration = track.durationSeconds || 0;
    const position = duration ? Math.min(state.position, duration) : state.position;
    const chapter = chapterAt(track, position);
    const artist = [chapter && chapter.title, track.artist, track.album !== track.title && track.album].filter(Boolean).join(" · ");
    set("artist", artist, (text) => (el.artist.textContent = text));
    set("paused", state.mark.playing, (playing) => (el.paused.hidden = playing));
    set("elapsed", time(position), (text) => (el.elapsed.textContent = text));
    const ratio = duration ? Math.min(1, position / duration) : 0;
    set("bar", Math.round(ratio * 500) / 500, (value) => (el.bar.style.transform = `scaleX(${value})`));
    drawLyrics(position, false);
  }
  setInterval(draw, TICK_MS);
})();
