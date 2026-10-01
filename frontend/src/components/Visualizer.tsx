import { useEffect, useRef, useState } from "react";

import { frameLoop } from "../frames";
import { analyserFor } from "../player/audioGraph";
import { usePlayer } from "../player/PlayerContext";
import { useFrameRate } from "../preferences/lowPower";

/**
 * Frequency bars of what is playing, in the canvas' CSS color (the accent). Draws only
 * while playing (and browsers pause animation frames in hidden tabs), at fewer frames
 * with "Lighter animations".
 */
export function Visualizer({ className = "", bars = 48 }: { className?: string; bars?: number }) {
  const { engine, state, remote } = usePlayer();
  const canvas = useRef<HTMLCanvasElement>(null);
  const playing = state.playing;
  const fps = useFrameRate();
  // Not shown (hidden by the layout, e.g. Now playing on phones): no Web Audio at all
  // until it is, playback then goes straight to the speakers.
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setShown(element.getClientRects().length > 0 && element.clientWidth > 0));
    observer.observe(element);
    return () => observer.disconnect();
  }, [remote]);

  useEffect(() => {
    const element = canvas.current;
    if (!element || !shown) return;
    const analyser = analyserFor(engine);
    const context = element.getContext("2d");
    if (!analyser || !context) return;
    const data = new Uint8Array(analyser.frequencyBinCount);
    // Up to ~16 kHz (the top of the spectrum is mostly empty), low frequencies spread out.
    const usable = Math.floor(data.length * 0.72);
    // The accent, read when the theme or the accent changes: reading it at every frame
    // made the browser recompute the page's styles each time.
    let color = getComputedStyle(element).color;
    const themes = new MutationObserver(() => {
      color = getComputedStyle(element).color;
    });
    themes.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-accent"] });

    const draw = () => {
      const ratio = window.devicePixelRatio || 1;
      const width = Math.round(element.clientWidth * ratio);
      const height = Math.round(element.clientHeight * ratio);
      if (element.width !== width || element.height !== height) {
        element.width = width;
        element.height = height;
      }
      analyser.getByteFrequencyData(data);
      if (!playing) data.fill(0); // paused: flat bars, not the last frame frozen
      context.clearRect(0, 0, width, height);
      context.fillStyle = color;
      const slot = width / bars;
      const barWidth = Math.max(1, slot * 0.7);
      for (let i = 0; i < bars; i++) {
        const from = Math.floor((i / bars) ** 2 * usable);
        const to = Math.max(from + 1, Math.floor(((i + 1) / bars) ** 2 * usable));
        let peak = 0;
        for (let bin = from; bin < to; bin++) peak = Math.max(peak, data[bin] ?? 0);
        const barHeight = Math.max(ratio, (peak / 255) ** 1.4 * height);
        context.fillRect(i * slot + (slot - barWidth) / 2, height - barHeight, barWidth, barHeight);
      }
    };
    draw();
    const stop = playing ? frameLoop(draw, fps) : null; // paused: flat bars, drawn once
    return () => {
      stop?.();
      themes.disconnect();
    };
  }, [engine, bars, playing, shown, fps]);

  // Remote mode: nothing plays in this tab to show.
  if (remote) return null;
  return <canvas ref={canvas} className={`visualizer ${className}`.trim()} aria-hidden />;
}
