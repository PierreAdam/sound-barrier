// Animation loops limited to a frame rate ("Lighter animations", preferences/lowPower.ts).

/**
 * Calls `draw` at each animation frame, at most `fps` times a second (null: every frame),
 * with the milliseconds since its previous call. Returns the function that stops it.
 */
export function frameLoop(draw: (now: number, elapsed: number) => void, fps: number | null): () => void {
  // A little under the interval: frames come at the display's rate, a hair early or late.
  const interval = fps ? 1000 / fps - 2 : 0;
  let last = performance.now();
  let frame = requestAnimationFrame(function tick(now) {
    frame = requestAnimationFrame(tick);
    if (now - last < interval) return;
    const elapsed = now - last;
    last = now;
    draw(now, elapsed);
  });
  return () => cancelAnimationFrame(frame);
}
