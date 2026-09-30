import { describe, expect, it } from "vitest";

import { spokenCrumbs } from "./SpokenPages";

describe("spokenCrumbs", () => {
  it("puts a book under its series", () => {
    expect(spokenCrumbs("audiobooks", { id: "b1", title: "Book Two", series: "The Saga" })).toEqual([
      { label: "Audiobooks", to: "/audiobooks" },
      { label: "The Saga", to: "/audiobooks/series/The%20Saga" },
      { label: "Book Two" },
    ]);
  });

  it("links the show itself from a page under it", () => {
    expect(spokenCrumbs("podcasts", { id: "p1", title: "The Show", series: "ignored" }, false)).toEqual([
      { label: "Podcasts", to: "/podcasts" },
      { label: "The Show", to: "/podcasts/p1" },
    ]);
  });

  it("has no series level for a book without one", () => {
    expect(spokenCrumbs("audiobooks", { id: "b2", title: "Alone", series: null }).map((c) => c.label)).toEqual([
      "Audiobooks",
      "Alone",
    ]);
  });
});
