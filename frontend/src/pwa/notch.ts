// Landscape on an iPhone: iOS reports the same safe-area inset on both sides, although the
// notch / Dynamic Island is on one only. The rotation tells which: <html data-notch="left"
// | "right">, and theme.less keeps only that side clear (none in portrait).

export type NotchSide = "left" | "right" | null;

/** The side the top of the phone is on, for a screen rotation in degrees. */
export function notchSide(angle: number): NotchSide {
  const turned = ((angle % 360) + 360) % 360;
  if (turned === 90) return "left"; // turned counterclockwise: its top is on the left
  if (turned === 270) return "right"; // clockwise (iOS' window.orientation says -90)
  return null;
}

function currentAngle(): number {
  const angle = window.screen?.orientation?.angle;
  if (typeof angle === "number") return angle;
  const legacy = (window as Window & { orientation?: number }).orientation; // iOS before 16.4
  return typeof legacy === "number" ? legacy : 0;
}

function update(): void {
  const side = notchSide(currentAngle());
  if (side) document.documentElement.dataset.notch = side;
  else delete document.documentElement.dataset.notch;
}

/** Call once at start-up. */
export function watchNotchSide(): void {
  update();
  window.screen?.orientation?.addEventListener?.("change", update);
  window.addEventListener("orientationchange", update);
  window.addEventListener("resize", update); // some browsers only fire this
}
