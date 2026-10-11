import { describe, expect, it } from "vitest";

import { DEFAULT_STREAM_OPTIONS, streamUrlWith } from "./streamUrl";

const URL_ = "https://music.example.com/api/stream/abc-123";

describe("streamUrlWith", () => {
  it("leaves the defaults out", () => {
    expect(streamUrlWith(URL_, DEFAULT_STREAM_OPTIONS)).toBe(URL_);
  });

  it("writes the options changed", () => {
    expect(streamUrlWith(URL_, { bitRate: 128, burst: 8, titles: false })).toBe(
      `${URL_}?bitrate=128&burst=8&titles=0`,
    );
    expect(streamUrlWith(URL_, { ...DEFAULT_STREAM_OPTIONS, burst: 0.5 })).toBe(`${URL_}?burst=0.5`);
  });
});
