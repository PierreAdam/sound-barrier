import { type ReactNode, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

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
  children,
}: {
  className?: string;
  buttonClassName: string;
  label: string; // accessible name of the button
  title?: string;
  button: ReactNode; // its content
  up?: boolean; // the panel opens above (the player bar)
  children(close: () => void): ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const location = useLocation();

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className={`dropdown ${className}`.trim()} ref={root}>
      <button
        className={`${buttonClassName}${open ? " dropdown__button--open" : ""}`}
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="menu"
        title={title}
        onClick={() => setOpen((value) => !value)}
      >
        {button}
      </button>
      {open && (
        <div className={`dropdown__panel${up ? " dropdown__panel--up" : ""}`} role="menu">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}
