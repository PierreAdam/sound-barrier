import { describe, expect, it } from "vitest";

import { formatSize } from "./format";

describe("formatSize", () => {
  it("picks the unit from the size", () => {
    expect(formatSize(1)).toBe("1 KB");
    expect(formatSize(512_000)).toBe("512 KB");
    expect(formatSize(10_485_760)).toBe("10.5 MB");
    expect(formatSize(245_000_000_000)).toBe("245.0 GB");
    expect(formatSize(1_830_000_000_000)).toBe("1.83 TB");
    expect(formatSize(undefined)).toBe("");
  });
});
