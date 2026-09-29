import { describe, expect, it } from "vitest";

import { bumpCovers, coverVersion } from "./coverVersions";

describe("cover versions", () => {
  it("gives a changed cover a new URL parameter, the others none", () => {
    expect(coverVersion("a")).toEqual({});
    bumpCovers("a", null, undefined);
    const first = coverVersion("a").rev;
    expect(first).toBeTypeOf("number");
    expect(coverVersion("b")).toEqual({});
    expect(coverVersion(undefined)).toEqual({});
  });
});
