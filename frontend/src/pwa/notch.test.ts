import { describe, expect, it } from "vitest";

import { notchSide } from "./notch";

describe("notch side", () => {
  it("follows the rotation", () => {
    expect(notchSide(0)).toBeNull(); // portrait: on top
    expect(notchSide(180)).toBeNull();
    expect(notchSide(90)).toBe("left");
    expect(notchSide(270)).toBe("right");
    expect(notchSide(-90)).toBe("right"); // iOS' window.orientation
  });
});
