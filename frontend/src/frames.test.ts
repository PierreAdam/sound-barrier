import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { frameLoop } from "./frames";

// Animation frames driven by hand: `frame(now)` runs the callbacks waiting for it.
let waiting: FrameRequestCallback[] = [];
const frame = (now: number) => {
  const run = waiting;
  waiting = [];
  run.forEach((callback) => callback(now));
};

beforeEach(() => {
  waiting = [];
  vi.spyOn(performance, "now").mockReturnValue(0);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => waiting.push(callback));
  vi.stubGlobal("cancelAnimationFrame", () => (waiting = []));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("frameLoop", () => {
  it("draws every frame without a limit", () => {
    const draw = vi.fn();
    frameLoop(draw, null);
    for (let i = 1; i <= 6; i++) frame(i * 16.7);
    expect(draw).toHaveBeenCalledTimes(6);
  });

  it("draws at most `fps` times a second, with the time since the last draw", () => {
    const elapsed: number[] = [];
    frameLoop((_, ms) => elapsed.push(Math.round(ms)), 20);
    for (let i = 1; i <= 60; i++) frame(i * (1000 / 60)); // one second at 60 Hz
    expect(elapsed.length).toBe(20);
    expect(elapsed.every((ms) => ms === 50)).toBe(true);
  });

  it("stops", () => {
    const draw = vi.fn();
    const stop = frameLoop(draw, null);
    frame(16);
    stop();
    frame(32);
    expect(draw).toHaveBeenCalledTimes(1);
  });
});
