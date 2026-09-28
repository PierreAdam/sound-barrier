import type { CSSProperties } from "react";
import { Link } from "react-router-dom";

import { formatTime } from "../format";
import { usePlayer } from "../player/PlayerContext";
import { CoverArt } from "./CoverArt";
import {
  CrossfadeIcon,
  NextIcon,
  PauseIcon,
  PlayIcon,
  PreviousIcon,
  QueueIcon,
  RepeatIcon,
  ShuffleIcon,
  VolumeIcon,
} from "./Icons";

const REPEAT_LABELS = { off: "Repeat: off", all: "Repeat: all", one: "Repeat: this track" } as const;

/**
 * Always-visible player: seekable progress line on top; cover, title and artist on the
 * left; transport controls in the middle; crossfade, time and volume on the right.
 */
export function PlayerBar({ queueOpen, onToggleQueue }: { queueOpen: boolean; onToggleQueue(): void }) {
  const { state, engine } = usePlayer();
  const { current } = state;
  const disabled = current === null;
  const progress = state.duration > 0 ? Math.min(100, (state.position / state.duration) * 100) : 0;

  return (
    <footer className="player" aria-label="Player">
      <input
        className="player__seek"
        type="range"
        aria-label="Seek"
        min={0}
        max={state.duration || 1}
        step={1}
        value={Math.min(state.position, state.duration || 0)}
        disabled={disabled}
        style={{ "--progress": `${progress}%` } as CSSProperties}
        onChange={(e) => engine.seek(Number(e.target.value))}
      />

      <div className="player__track">
        <CoverArt id={current?.coverArt} size={56} className="player__cover" />
        <div className="player__meta">
          {current ? (
            <>
              <span className="player__title" title={current.title}>
                {current.albumId ? <Link to={`/albums/${current.albumId}`}>{current.title}</Link> : current.title}
              </span>
              <span className="player__artist" title={current.artist}>
                {current.artistId ? <Link to={`/artists/${current.artistId}`}>{current.artist}</Link> : current.artist}
              </span>
            </>
          ) : (
            <>
              <span className="player__title">Nothing playing</span>
              <span className="player__artist">Pick an album in Browse</span>
            </>
          )}
        </div>
      </div>

      <div className="player__controls">
        <button
          className={`icon-button${state.shuffle ? " icon-button--active" : ""}`}
          type="button"
          aria-label="Shuffle"
          aria-pressed={state.shuffle}
          title={state.shuffle ? "Shuffle: on" : "Shuffle: off"}
          onClick={() => engine.toggleShuffle()}
        >
          <ShuffleIcon />
        </button>
        <button className="icon-button" type="button" aria-label="Previous" disabled={disabled} onClick={() => engine.previous()}>
          <PreviousIcon />
        </button>
        <button
          className="icon-button icon-button--primary"
          type="button"
          aria-label={state.playing ? "Pause" : "Play"}
          disabled={disabled}
          onClick={() => engine.togglePlay()}
        >
          {state.playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        <button className="icon-button" type="button" aria-label="Next" disabled={!state.hasNext} onClick={() => engine.next()}>
          <NextIcon />
        </button>
        <button
          className={`icon-button${state.repeat !== "off" ? " icon-button--active" : ""}`}
          type="button"
          aria-label={REPEAT_LABELS[state.repeat]}
          title={REPEAT_LABELS[state.repeat]}
          onClick={() => engine.cycleRepeat()}
        >
          <RepeatIcon one={state.repeat === "one"} />
        </button>
      </div>

      <div className="player__right">
        <button
          className={`icon-button player__queue${queueOpen ? " icon-button--active" : ""}`}
          type="button"
          aria-label="Queue"
          aria-expanded={queueOpen}
          title={`Queue (${state.queue.length})`}
          onClick={onToggleQueue}
        >
          <QueueIcon />
        </button>
        <button
          className={`icon-button player__crossfade${state.crossfade ? " icon-button--active" : ""}`}
          type="button"
          aria-label="Crossfade"
          aria-pressed={state.crossfade}
          title={state.crossfade ? `Crossfade: ${state.crossfadeSeconds} s (change in Settings)` : "Crossfade: off"}
          onClick={() => engine.toggleCrossfade()}
        >
          <CrossfadeIcon />
          {state.crossfade && <span className="player__crossfade-seconds">{state.crossfadeSeconds}s</span>}
        </button>
        <span className="player__time">
          {formatTime(state.position)} / {formatTime(state.duration)}
        </span>
        <div className="player__volume">
          <button
            className="icon-button"
            type="button"
            aria-label={state.muted ? "Unmute" : "Mute"}
            onClick={() => engine.toggleMute()}
          >
            <VolumeIcon muted={state.muted || state.volume === 0} />
          </button>
          <input
            className="slider"
            type="range"
            aria-label="Volume"
            min={0}
            max={1}
            step={0.01}
            value={state.muted ? 0 : state.volume}
            onChange={(e) => engine.setVolume(Number(e.target.value))}
          />
        </div>
      </div>
    </footer>
  );
}
