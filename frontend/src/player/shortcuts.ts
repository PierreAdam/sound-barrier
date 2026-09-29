// Keyboard shortcuts of the player: Space plays / pauses, ← / → go 10 s back / forward.
// They never steal a key from what has the focus and needs it: text fields, lists,
// editable areas (all keys); buttons (Space clicks them); sliders and menus (arrows).

export const SEEK_STEP_S = 10;

type Action = "toggle" | "back" | "forward";

const TEXT_INPUTS = new Set(["text", "search", "email", "password", "number", "url", "tel", "date", "time"]);

function typing(element: Element): boolean {
  if (element instanceof HTMLElement && element.isContentEditable) return true;
  if (element.closest('[contenteditable]:not([contenteditable="false"])')) return true;
  if (element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) return true;
  if (element instanceof HTMLInputElement) return TEXT_INPUTS.has(element.type) || element.type === "";
  return element.getAttribute("role") === "textbox";
}

function usesSpace(element: Element): boolean {
  return (
    element instanceof HTMLButtonElement ||
    element instanceof HTMLAnchorElement ||
    element instanceof HTMLInputElement || // checkboxes, radios, sliders
    ["button", "checkbox", "menuitem", "menuitemcheckbox", "option", "tab", "switch"].includes(
      element.getAttribute("role") ?? "",
    )
  );
}

function usesArrows(element: Element): boolean {
  if (element instanceof HTMLInputElement) return true; // sliders, radios
  return element.closest('[role="menu"], [role="listbox"], [role="tablist"], [role="slider"]') !== null;
}

/** The player action of a key press, or null when the key belongs to something else. */
export function shortcutFor(event: KeyboardEvent): Action | null {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return null;
  const target = event.target instanceof Element ? event.target : null;
  if (target && typing(target)) return null;
  if (event.key === " " || event.code === "Space") {
    if (event.repeat || (target && usesSpace(target))) return null;
    return "toggle";
  }
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    if (target && usesArrows(target)) return null;
    return event.key === "ArrowLeft" ? "back" : "forward";
  }
  return null;
}

/**
 * onMouseDown of an area whose buttons should not take the focus when clicked with the
 * mouse (the player bar, the lyrics): a focused button would take the next Space press
 * (e.g. Space after clicking "Next" would skip again). Keyboard focus (Tab) still works;
 * sliders and text fields keep their normal behavior.
 */
export function keepFocus(event: { target: EventTarget; preventDefault(): void }): void {
  const target = event.target instanceof Element ? event.target : null;
  if (target?.closest("button") && !target.closest("input, textarea, select")) event.preventDefault();
}
