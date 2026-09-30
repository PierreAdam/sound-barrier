// Web Audio analyser for the visualizers, fed by both decks of the player.
//
// Created the first time a visualizer is shown (never before: until then playback does
// not depend on Web Audio at all). A media element can only be connected once, so the
// graph is kept for the whole page life. Streams come from our own origin: the analyser
// can read them (cross-origin audio would be silent once connected).

import type { PlayerController } from "./controller";

interface Graph {
  context: AudioContext;
  analyser: AnalyserNode;
}

let graph: Graph | null = null;

export function analyserFor(engine: PlayerController): AnalyserNode | null {
  if (graph) {
    resumeAudio();
    return graph.analyser;
  }
  if (typeof window.AudioContext !== "function") return null;
  const elements = engine.audioElements.filter((e): e is HTMLAudioElement => e instanceof HTMLMediaElement);
  if (!elements.length) return null;
  const context = new AudioContext();
  const analyser = context.createAnalyser();
  analyser.fftSize = 512;
  analyser.smoothingTimeConstant = 0.78;
  for (const element of elements) context.createMediaElementSource(element).connect(analyser);
  analyser.connect(context.destination);
  graph = { context, analyser };
  resumeAudio();
  return analyser;
}

/** Browsers start (or leave) an AudioContext suspended until a user gesture: while it is,
 * the connected decks are silent. Called on play. */
export function resumeAudio(): void {
  if (graph?.context.state === "suspended") void graph.context.resume();
}
