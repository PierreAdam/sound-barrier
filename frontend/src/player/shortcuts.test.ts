import { afterEach, describe, expect, it } from "vitest";

import { shortcutFor } from "./shortcuts";

function press(key: string, target: Element, init: KeyboardEventInit = {}): KeyboardEvent {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
  Object.defineProperty(event, "target", { value: target });
  return event;
}

function element(html: string): Element {
  document.body.innerHTML = html;
  return document.body.firstElementChild as Element;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("shortcutFor", () => {
  it("plays, pauses and seeks from the page", () => {
    expect(shortcutFor(press(" ", document.body))).toBe("toggle");
    expect(shortcutFor(press("ArrowLeft", document.body))).toBe("back");
    expect(shortcutFor(press("ArrowRight", document.body))).toBe("forward");
    expect(shortcutFor(press("a", document.body))).toBeNull();
  });

  it("leaves every key to text fields", () => {
    for (const html of ['<input type="search">', "<input>", "<textarea></textarea>", "<select></select>", '<div contenteditable="true"></div>']) {
      const field = element(html);
      expect(shortcutFor(press(" ", field)), html).toBeNull();
      expect(shortcutFor(press("ArrowLeft", field)), html).toBeNull();
    }
  });

  it("leaves Space to buttons and arrows to sliders and menus", () => {
    const button = element("<button>Next</button>");
    expect(shortcutFor(press(" ", button))).toBeNull();
    expect(shortcutFor(press("ArrowRight", button))).toBe("forward");
    expect(shortcutFor(press("ArrowRight", element('<input type="range">')))).toBeNull();
    const item = element('<div role="menu"><button role="menuitem">A</button></div>').firstElementChild as Element;
    expect(shortcutFor(press("ArrowLeft", item))).toBeNull();
  });

  it("ignores modifiers and held keys", () => {
    expect(shortcutFor(press("ArrowLeft", document.body, { ctrlKey: true }))).toBeNull();
    expect(shortcutFor(press(" ", document.body, { repeat: true }))).toBeNull();
  });
});
