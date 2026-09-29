import { type CSSProperties, type JSX, useState } from "react";
import { Link } from "react-router-dom";

import { formatTime } from "../format";
import { usePlayer } from "../player/PlayerContext";
import { CoverArt } from "./CoverArt";
import { Dropdown } from "./Dropdown";
import { useNowPlaying } from "./NowPlaying";
import { Visualizer } from "./Visualizer";
import {
  CrossfadeIcon,
  LyricsIcon,
  MoreIcon,
  NextIcon,
  PauseIcon,
  PlayIcon,
  PreviousIcon,
  QueueIcon,
  RepeatIcon,
  ShuffleIcon,
  VisualizerIcon,
  VolumeIcon,
} from "./Icons";

// The small visualizer of the player bar: per browser, like the volume.
const MINI_VISUALIZER_KEY = "sb.player.visualizer";

function storedVisualizer(): boolean {
  try {
    return localStorage.getItem(MINI_VISUALIZER_KEY) === "1";
  } catch {
    return false;
  }
}

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
  const nowPlaying = useNowPlaying();
  const [miniVisualizer, setMiniVisualizer] = useState(storedVisualizer);

  function toggleVisualizer() {
    const next = !miniVisualizer;
    setMiniVisualizer(next);
    try {
      localStorage.setItem(MINI_VISUALIZER_KEY, next ? "1" : "0");
    } catch {
      // private browsing: only for this page
    }
  }

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
        <button
          className="player__cover-button"
          type="button"
          aria-label="Now playing: lyrics and visualizer"
          disabled={disabled}
          onClick={nowPlaying.toggle}
        >
          <CoverArt id={current?.coverArt} size={56} className="player__cover" />
        </button>
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
        {miniVisualizer && !disabled && <Visualizer className="player__visualizer" bars={16} />}
      </div>

      <div className="player__controls">
        <button
          className={`icon-button player__shuffle${state.shuffle ? " icon-button--active" : ""}`}
          type="button"
          aria-label="Shuffle"
          aria-pressed={state.shuffle}
          title={state.shuffle ? "Shuffle: on" : "Shuffle: off"}
          onClick={() => engine.toggleShuffle()}
        >
          <ShuffleIcon />
        </button>
        <button className="icon-button player__previous" type="button" aria-label="Previous" disabled={disabled} onClick={() => engine.previous()}>
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
          className={`icon-button player__repeat${state.repeat !== "off" ? " icon-button--active" : ""}`}
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
          className={`icon-button player__now-playing${nowPlaying.open ? " icon-button--active" : ""}`}
          type="button"
          aria-label="Now playing: lyrics and visualizer"
          aria-pressed={nowPlaying.open}
          title="Now playing: lyrics and visualizer"
          disabled={disabled}
          onClick={nowPlaying.toggle}
        >
          <LyricsIcon />
        </button>
        <button
          className={`icon-button player__visualizer-toggle${miniVisualizer ? " icon-button--active" : ""}`}
          type="button"
          aria-label="Visualizer in the player bar"
          aria-pressed={miniVisualizer}
          title={miniVisualizer ? "Visualizer: on" : "Visualizer: off"}
          onClick={toggleVisualizer}
        >
          <VisualizerIcon />
        </button>
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
        <PlayerMenu miniVisualizer={miniVisualizer} onToggleVisualizer={toggleVisualizer} />
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

/**
 * "⋯": the controls the bar has no room for (it shows once some collapse, see the
 * container queries of .player in theme.less). It holds all of them, always.
 */
function PlayerMenu({ miniVisualizer, onToggleVisualizer }: { miniVisualizer: boolean; onToggleVisualizer(): void }) {
  const { state, engine } = usePlayer();

  const item = (label: string, active: boolean, onClick: () => void, icon: JSX.Element) => (
    <button
      className={`dropdown__item${active ? " dropdown__item--active" : ""}`}
      type="button"
      role="menuitemcheckbox"
      aria-checked={active}
      onClick={onClick}
    >
      {icon}
      {label}
    </button>
  );

  return (
    <Dropdown className="player__more" buttonClassName="icon-button" label="More controls" title="More controls" button={<MoreIcon />} up>
      {() => (
        <>
          {state.current && (
            <p className="dropdown__header player-menu__time">
              {formatTime(state.position)} / {formatTime(state.duration)}
            </p>
          )}
          {item(state.shuffle ? "Shuffle: on" : "Shuffle: off", state.shuffle, () => engine.toggleShuffle(), <ShuffleIcon />)}
          {item(REPEAT_LABELS[state.repeat], state.repeat !== "off", () => engine.cycleRepeat(), <RepeatIcon one={state.repeat === "one"} />)}
          {item(
            state.crossfade ? `Crossfade: ${state.crossfadeSeconds} s` : "Crossfade: off",
            state.crossfade,
            () => engine.toggleCrossfade(),
            <CrossfadeIcon />,
          )}
          {item(miniVisualizer ? "Visualizer: on" : "Visualizer: off", miniVisualizer, onToggleVisualizer, <VisualizerIcon />)}
          <label className="player-menu__volume">
            <VolumeIcon muted={state.muted || state.volume === 0} />
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
          </label>
        </>
      )}
    </Dropdown>
  );
}
