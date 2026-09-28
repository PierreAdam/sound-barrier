import { describe, expect, it, vi } from "vitest";

import { createScrobbler } from "./scrobble";

function setup() {
  const nowPlaying = vi.fn();
  const played = vi.fn();
  const feed = createScrobbler({ nowPlaying, played }, () => 1000);
  const at = (position: number, extra: Partial<Parameters<typeof feed>[0]> = {}) =>
    feed({ key: 1, trackId: "a", playing: true, position, duration: 200, ...extra });
  return { nowPlaying, played, feed, at };
}

describe("createScrobbler", () => {
  it("reports now playing at start and one play past half the track", () => {
    const { nowPlaying, played, at } = setup();
    at(0);
    at(50);
    expect(nowPlaying).toHaveBeenCalledWith("a");
    expect(played).not.toHaveBeenCalled();
    at(100);
    at(150);
    expect(played).toHaveBeenCalledTimes(1);
    expect(played).toHaveBeenCalledWith("a", 1000);
    expect(nowPlaying).toHaveBeenCalledTimes(1);
  });

  it("counts long tracks after 4 minutes and ignores very short ones", () => {
    const long = setup();
    long.at(239, { duration: 1200 });
    expect(long.played).not.toHaveBeenCalled();
    long.at(240, { duration: 1200 });
    expect(long.played).toHaveBeenCalledTimes(1);

    const short = setup();
    short.at(20, { duration: 25 });
    expect(short.played).not.toHaveBeenCalled();
  });

  it("counts again when the track restarts or another entry plays", () => {
    const { played, at } = setup();
    at(150);
    at(0.5); // repeat one: back to the start
    at(150);
    expect(played).toHaveBeenCalledTimes(2);
    at(150, { key: 2, trackId: "b" });
    expect(played).toHaveBeenCalledTimes(3);
  });

  it("does nothing while paused", () => {
    const { nowPlaying, played, at } = setup();
    at(150, { playing: false });
    expect(nowPlaying).not.toHaveBeenCalled();
    expect(played).not.toHaveBeenCalled();
  });
});
