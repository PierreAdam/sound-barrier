import { describe, expect, it, vi } from "vitest";

import { createRevisionCheck } from "./useLibraryWatcher";

function setup(visible: boolean) {
  const state = { revision: 1, visible };
  const onChange = vi.fn();
  const check = createRevisionCheck(
    () => Promise.resolve(state.revision),
    onChange,
    () => state.visible,
  );
  return { state, onChange, check };
}

describe("createRevisionCheck", () => {
  it("calls onChange only when the revision moves", async () => {
    const { state, onChange, check } = setup(true);
    await check();
    await check();
    expect(onChange).not.toHaveBeenCalled();
    state.revision = 2;
    await check();
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("notices a change made while the tab was hidden since it opened", async () => {
    const { state, onChange, check } = setup(false);
    await check(); // opened in a hidden tab: sets the reference anyway
    state.revision = 2; // e.g. an import finishes
    await check(); // still hidden: skipped
    expect(onChange).not.toHaveBeenCalled();
    state.visible = true;
    await check(); // visible again
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("ignores failed requests", async () => {
    const onChange = vi.fn();
    const check = createRevisionCheck(() => Promise.reject(new Error("offline")), onChange, () => true);
    await check();
    expect(onChange).not.toHaveBeenCalled();
  });
});
