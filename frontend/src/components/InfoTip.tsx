import { type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { InfoIcon } from "./Icons";

const WIDTH = 280;
const MARGIN = 8; // from the icon, and from the window's edges

/**
 * An ⓘ that explains a concept in a small popup: on hover (mouse), on focus (keyboard),
 * on tap (touch screens, tap again or elsewhere to close). The popup is placed against
 * the window (rendered in <body>): a menu that scrolls does not clip it. Text only: it
 * takes no clicks (a click there must not close the menu it explains).
 */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const [place, setPlace] = useState<{ left: number; top: number; above: boolean } | null>(null);
  const [pinned, setPinned] = useState(false); // opened by a tap

  const show = useCallback(() => {
    const rect = button.current?.getBoundingClientRect();
    if (!rect) return;
    const left = Math.min(Math.max(rect.left + rect.width / 2 - WIDTH / 2, MARGIN), window.innerWidth - WIDTH - MARGIN);
    // Below the icon, unless it is in the lower part of the window.
    const above = rect.bottom > window.innerHeight * 0.6;
    setPlace({ left, top: above ? rect.top - MARGIN : rect.bottom + MARGIN, above });
  }, []);

  const hide = useCallback(() => {
    setPinned(false);
    setPlace(null);
  }, []);

  useEffect(() => {
    if (!place) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation(); // the tip, not the menu around it
      hide();
    };
    const onScroll = () => hide();
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [place, hide]);

  // Tapped open: closed by a tap anywhere else.
  useEffect(() => {
    if (!pinned) return;
    const onDown = (event: PointerEvent) => {
      if (!button.current?.contains(event.target as Node)) hide();
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [pinned, hide]);

  return (
    <>
      <button
        ref={button}
        className="info-tip"
        type="button"
        aria-label={label}
        aria-describedby={place ? id : undefined}
        aria-expanded={place !== null}
        onMouseEnter={show}
        onMouseLeave={() => !pinned && hide()}
        onFocus={show}
        onBlur={hide}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation(); // inside a <label> or a menu item: not theirs
          if (pinned) hide();
          else {
            show();
            setPinned(true);
          }
        }}
      >
        <InfoIcon />
      </button>
      {place &&
        createPortal(
          <div
            id={id}
            role="tooltip"
            className={`info-tip__popup${place.above ? " info-tip__popup--above" : ""}`}
            style={{ left: place.left, top: place.top, width: WIDTH }}
          >
            {children}
          </div>,
          document.body,
        )}
    </>
  );
}
