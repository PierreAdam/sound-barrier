import { useEffect, useRef } from "react";

import { analyserFor } from "../player/audioGraph";
import { usePlayer } from "../player/PlayerContext";

/**
 * Frequency bars of what is playing, in the canvas' CSS color (the accent). Draws only
 * while playing (and browsers pause animation frames in hidden tabs).
 */
export function Visualizer({ className = "", bars = 48 }: { className?: string; bars?: number }) {
  const { engine, state, remote } = usePlayer();
  const canvas = useRef<HTMLCanvasElement>(null);
  const playing = state.playing;

  useEffect(() => {
    const element = canvas.current;
    const analyser = analyserFor(engine);
    const context = element?.getContext("2d");
    if (!element || !analyser || !context) return;
    const data = new Uint8Array(analyser.frequencyBinCount);
    // Up to ~16 kHz (the top of the spectrum is mostly empty), low frequencies spread out.
    const usable = Math.floor(data.length * 0.72);
    let frame = 0;

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
      context.fillStyle = getComputedStyle(element).color;
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
      if (playing) frame = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [engine, bars, playing]);

  // Remote mode: nothing plays in this tab to show.
  if (remote) return null;
  return <canvas ref={canvas} className={`visualizer ${className}`.trim()} aria-hidden />;
}
