import { describe, expect, it } from "vitest";

import { DEFAULT_RADIO_OPTIONS, parseRadioUrl, radioTextUrl, radioUrl } from "./options";

const STREAM = "https://music.example.com/api/stream/abc-123";

describe("radio page URL", () => {
  it("leaves the defaults out", () => {
    expect(radioUrl(STREAM, DEFAULT_RADIO_OPTIONS)).toBe("https://music.example.com/radio/abc-123");
  });

  it("goes there and back", () => {
    const options = {
      layout: "banner",
      theme: "light",
      accent: "violet",
      upcoming: 0,
      delay: 10,
      cover: false,
      listeners: false,
      ratio: "16:9",
      width: 1024,
    } as const;
    const url = radioUrl(STREAM, options);
    expect(url).toBe(
      "https://music.example.com/radio/abc-123?layout=banner&theme=light&accent=violet&next=0&delay=10&cover=0&listeners=0&ratio=16%3A9&width=1024",
    );
    expect(parseRadioUrl(url)).toEqual({ key: "abc-123", options });
  });

  it("keeps values in range, ignores unknown ones", () => {
    const { options } = parseRadioUrl("https://x.test/radio/k?next=99&delay=-5&theme=neon&accent=gold&layout=x&ratio=2:1&width=9999");
    expect(options).toEqual({ ...DEFAULT_RADIO_OPTIONS, upcoming: 20, delay: 0, width: 4096 });
    expect(parseRadioUrl("https://x.test/radio.html?key=k2").key).toBe("k2");
    expect(parseRadioUrl("https://x.test/radio.html").key).toBeNull();
  });

  it("has a plain text version", () => {
    expect(radioTextUrl(STREAM, { ...DEFAULT_RADIO_OPTIONS, upcoming: 1, delay: 10 })).toBe(
      `${STREAM}/info?format=text&next=1&delay=10`,
    );
  });
});
