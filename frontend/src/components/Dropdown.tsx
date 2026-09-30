import { type CSSProperties, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

const GAP = 8; // between the button and a `fixed` panel
const MARGIN = 8; // between a `fixed` panel and the window's edges

/**
 * A button opening a menu panel (top bar menus, the player's "⋯"). Closes on a click
 * outside, on Escape, on navigation, and when `children` calls `close`.
 */
export function Dropdown({
  className = "",
  buttonClassName,
  label,
  title,
  button,
  up = false,
  fixed = false,
  children,
}: {
  className?: string;
  buttonClassName: string;
  label: string; // accessible name of the button
  title?: string;
  button: ReactNode; // its content
  up?: boolean; // the panel opens above (the player bar)
  // The panel is placed against the window: not clipped by a parent that hides what
  // overflows (the queue panel's slot). Under the button, else above it when there is
  // more room there, always inside the window (scrolling if taller).
  fixed?: boolean;
  children(close: () => void): ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<CSSProperties | undefined>(undefined);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const location = useLocation();

  // Placed once shown (its size is known then), before the browser paints it. Hidden
  // until then: never seen at a wrong place. Placed again when its content changes (it
  // may grow: a list arriving, a section opened), so it stays inside the window.
  useLayoutEffect(() => {
    if (!open || !fixed) {
      setPlace(undefined);
      return;
    }
    const menu = panel.current;
    if (!menu) return;
    let last = "";
    const position = () => {
      const button = trigger.current?.getBoundingClientRect();
      if (!button) return;
      const width = menu.offsetWidth;
      const height = menu.scrollHeight;
      const below = window.innerHeight - button.bottom - GAP - MARGIN;
      const above = button.top - GAP - MARGIN;
      const downward = height <= below || below >= above;
      // Anchored on the button's side: growing, it goes away from it, never off the window.
      const next: CSSProperties = {
        position: "fixed",
        top: downward ? button.bottom + GAP : "auto",
        bottom: downward ? "auto" : window.innerHeight - button.top + GAP,
        left: Math.max(MARGIN, Math.min(button.left, window.innerWidth - width - MARGIN)),
        right: "auto",
        maxHeight: downward ? below : above,
        overflowY: "auto",
      };
      const key = JSON.stringify(next);
      if (key === last) return;
      last = key;
      setPlace(next);
    };
    position();
    // Its content, not its own style (which this sets).
    const observer = new MutationObserver((changes) => {
      if (changes.some((change) => change.target !== menu)) position();
    });
    observer.observe(menu, { childList: true, subtree: true, characterData: true, attributes: true });
    return () => observer.disconnect();
  }, [open, fixed]);

  function toggle() {
    setOpen((value) => !value);
  }

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    // Placed once, when opened: the window changing size moves the button away.
    const onResize = () => fixed && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, [open, fixed]);

  return (
    <div className={`dropdown ${className}`.trim()} ref={root}>
      <button
        ref={trigger}
        className={`${buttonClassName}${open ? " dropdown__button--open" : ""}`}
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="menu"
        title={title}
        onClick={toggle}
      >
        {button}
      </button>
      {open && (
        <div
          className={`dropdown__panel${up ? " dropdown__panel--up" : ""}`}
          role="menu"
          ref={panel}
          style={fixed ? (place ?? { position: "fixed", visibility: "hidden" }) : undefined}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}
