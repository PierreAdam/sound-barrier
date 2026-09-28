// Sound-Barrier logo ("Mach play"): a play button inside its shock cone.
// Inline (not <img>) so hovering can play the flight animation once; the static
// logo comes back when the last animated element finishes.
// Standalone copies for other uses: public/logo.svg and public/logo-flight.svg.
import { useId, useState } from "react";

const CONE = "15,11 51,32 15,53";

export function BrandLogo({ className }: { className?: string }) {
  const [flying, setFlying] = useState(false);
  const clipId = useId();

  return (
    <svg
      className={`brand-logo${flying ? " brand-logo--flying" : ""}${className ? ` ${className}` : ""}`}
      viewBox="0 0 64 64"
      aria-hidden
      onMouseEnter={() => setFlying(true)}
    >
      <defs>
        <clipPath id={clipId}>
          <rect width="64" height="64" rx="14" />
        </clipPath>
      </defs>
      <rect className="brand-logo__tile" width="64" height="64" rx="14" />
      <g clipPath={`url(#${clipId})`}>
        <path className="brand-logo__air" d="M8 27 q1.5 -2 3 0 t3 0 t3 0" />
        <path className="brand-logo__air" d="M6 32 q1.5 -2 3 0 t3 0 t3 0 t3 0" />
        {/* Ends last (see the animation delays in theme.less): marks the end of the flight. */}
        <path className="brand-logo__air" d="M8 37 q1.5 -2 3 0 t3 0 t3 0" onAnimationEnd={() => setFlying(false)} />
      </g>
      <polyline className="brand-logo__cone" points={CONE} />
      <polyline className="brand-logo__front" points="51,32 15,11" />
      <polyline className="brand-logo__front" points="51,32 15,53" />
      <polygon className="brand-logo__plane" points="20,20 40,32 20,44" />
    </svg>
  );
}
