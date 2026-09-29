import { type CSSProperties, type JSX, useState } from "react";
import { Link } from "react-router-dom";

import { formatTime } from "../format";
import type { Track } from "../player/engine";
import { usePlayer, useResumeNotice } from "../player/PlayerContext";
import { usePreferences } from "../preferences/PreferencesContext";
import { keepFocus } from "../player/shortcuts";
import { albumUrl, artistUrl } from "../player/tracks";
import { CoverArt } from "./CoverArt";
import { Dropdown } from "./Dropdown";
import { useNowPlaying } from "./NowPlaying";
import { Visualizer } from "./Visualizer";
import {
  CrossfadeIcon,
  LyricsIcon,
  MoreIcon,
  NextIcon,
  PauseAtEndIcon,
  PauseIcon,
  PlayIcon,
  PreviousIcon,
  QueueIcon,
  RepeatIcon,
  ShuffleIcon,
  VisualizerIcon,
  VolumeIcon,
} from "./Icons";

// Playback speeds of podcasts and audiobooks (the speed button cycles through them).
const SPEEDS = [1, 1.25, 1.5, 1.75, 2];

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

/** "Pause at end of chapter" (of episode for a podcast), for the current track. */
function pauseAtEndLabel(track: Track | null): string {
  return track?.spokenKind === "podcasts" && !track.chapters ? "Pause at end of episode" : "Pause at end of chapter";
}

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
  const resume = useResumeNotice();
  const { preferences, update } = usePreferences();
  // Podcasts and audiobooks: short skips and a playback speed (music plays at 1x).
  const spoken = current?.longForm ?? false;
  const speed = preferences?.player.spokenSpeed ?? 1;
  const skip = (seconds: number) =>
    engine.seek(Math.min(Math.max(engine.currentTime + seconds, 0), Math.max(state.duration - 0.5, 0)));
  const nextSpeed = () => setSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length] ?? 1);
  const setSpeed = (next: number) =>
    update((current) => ({ ...current, player: { ...current.player, spokenSpeed: next } }));
  const pauseLabel = pauseAtEndLabel(current);
  const [miniVisualizer, setMiniVisualizer] = useState(storedVisualizer);
  const chapters = current?.chapters;
  const chapter = chapters?.[state.chapter];
  const titleUrl = current && albumUrl(current);
  const artistLink = current && artistUrl(current);

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
    // Mouse clicks on its buttons do not focus them: Space then still plays / pauses.
    <footer className="player" aria-label="Player" onMouseDown={keepFocus}>
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
      {chapters && state.duration > 0 && (
        // Where the chapters inside the file start.
        <div className="player__chapter-marks" aria-hidden="true">
          {chapters.slice(1).map((c) => (
            <span key={c.start} style={{ left: `${(c.start / state.duration) * 100}%` }} />
          ))}
        </div>
      )}

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
                {titleUrl ? <Link to={titleUrl}>{current.title}</Link> : current.title}
              </span>
              {resume.notice?.trackId === current.id ? (
                <span className="player__resumed" role="status">
                  Resumed at {formatTime(resume.notice.seconds)} ·{" "}
                  <button className="link-button" type="button" onClick={resume.startOver}>
                    Start over
                  </button>
                </span>
              ) : state.pauseAtEnd ? (
                // Also on phones, where the button is in the "⋯" menu.
                <span className="player__artist player__pause-note" role="status">
                  <PauseAtEndIcon /> Pauses at the end of {chapter ? `"${chapter.title}"` : "this file"}
                </span>
              ) : chapter ? (
                <span className="player__artist" title={`${chapter.title} · ${current.artist ?? ""}`}>
                  <span className="player__chapter">{chapter.title}</span> · {current.artist}
                </span>
              ) : (
                <span className="player__artist" title={current.artist}>
                  {artistLink ? <Link to={artistLink}>{current.artist}</Link> : current.artist}
                </span>
              )}
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
        {/* Shuffle, repeat and crossfade: not for audiobooks and podcasts. */}
        {!state.spoken && (
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
        )}
        <button
          className="icon-button player__previous"
          type="button"
          aria-label={chapters ? "Previous chapter" : "Previous"}
          title={chapters ? "Previous chapter" : undefined}
          disabled={disabled}
          onClick={() => engine.previous()}
        >
          <PreviousIcon />
        </button>
        {spoken && (
          <button className="icon-button player__skip" type="button" aria-label="15 seconds back" onClick={() => skip(-15)}>
            −15
          </button>
        )}
        <button
          className="icon-button icon-button--primary"
          type="button"
          aria-label={state.playing ? "Pause" : "Play"}
          disabled={disabled}
          onClick={() => engine.togglePlay()}
        >
          {state.playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        {spoken && (
          <button className="icon-button player__skip" type="button" aria-label="30 seconds forward" onClick={() => skip(30)}>
            +30
          </button>
        )}
        <button
          className="icon-button"
          type="button"
          aria-label={chapters ? "Next chapter" : "Next"}
          title={chapters ? "Next chapter" : undefined}
          disabled={!state.hasNext}
          onClick={() => engine.next()}
        >
          <NextIcon />
        </button>
        {!state.spoken && (
          <button
            className={`icon-button player__repeat${state.repeat !== "off" ? " icon-button--active" : ""}`}
            type="button"
            aria-label={REPEAT_LABELS[state.repeat]}
            title={REPEAT_LABELS[state.repeat]}
            onClick={() => engine.cycleRepeat()}
          >
            <RepeatIcon one={state.repeat === "one"} />
          </button>
        )}
      </div>

      <div className="player__right">
        {spoken && (
          <button
            className={`icon-button player__pause-at-end${state.pauseAtEnd ? " icon-button--active" : ""}`}
            type="button"
            aria-label={pauseLabel}
            aria-pressed={state.pauseAtEnd}
            title={state.pauseAtEnd ? `${pauseLabel}: on (click to cancel)` : pauseLabel}
            onClick={() => engine.setPauseAtEnd(!state.pauseAtEnd)}
          >
            <PauseAtEndIcon />
          </button>
        )}
        {spoken && (
          <button
            className={`icon-button player__speed${speed !== 1 ? " icon-button--active" : ""}`}
            type="button"
            aria-label={`Playback speed: ${speed}×`}
            title="Playback speed (podcasts and audiobooks)"
            disabled={!preferences}
            onClick={nextSpeed}
          >
            {speed}×
          </button>
        )}
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
        {!state.spoken && (
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
        )}
        <span className="player__time">
          {formatTime(state.position)} / {formatTime(state.duration)}
        </span>
        <PlayerMenu
          miniVisualizer={miniVisualizer}
          onToggleVisualizer={toggleVisualizer}
          speed={preferences ? speed : null}
          onSpeed={setSpeed}
          onSkip={skip}
        />
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
function PlayerMenu({
  miniVisualizer,
  onToggleVisualizer,
  speed,
  onSpeed,
  onSkip,
}: {
  miniVisualizer: boolean;
  onToggleVisualizer(): void;
  speed: number | null; // null: preferences not loaded yet
  onSpeed(speed: number): void;
  onSkip(seconds: number): void;
}) {
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
          {/* Not for audiobooks and podcasts. */}
          {!state.spoken && (
            <>
              {item(state.shuffle ? "Shuffle: on" : "Shuffle: off", state.shuffle, () => engine.toggleShuffle(), <ShuffleIcon />)}
              {item(REPEAT_LABELS[state.repeat], state.repeat !== "off", () => engine.cycleRepeat(), <RepeatIcon one={state.repeat === "one"} />)}
              {item(
                state.crossfade ? `Crossfade: ${state.crossfadeSeconds} s` : "Crossfade: off",
                state.crossfade,
                () => engine.toggleCrossfade(),
                <CrossfadeIcon />,
              )}
            </>
          )}
          {/* Audiobooks and podcasts: what phones have no room for in the bar. */}
          {state.spoken && (
            <>
              <div className="player-menu__row">
                <button className="button button--ghost" type="button" onClick={() => onSkip(-15)}>
                  −15 s
                </button>
                <button className="button button--ghost" type="button" onClick={() => onSkip(30)}>
                  +30 s
                </button>
              </div>
              {item(pauseAtEndLabel(state.current), state.pauseAtEnd, () => engine.setPauseAtEnd(!state.pauseAtEnd), <PauseAtEndIcon />)}
              {speed !== null && (
                <div className="player-menu__speeds" role="group" aria-label="Playback speed">
                  {SPEEDS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className={`player-menu__speed${s === speed ? " player-menu__speed--active" : ""}`}
                      aria-pressed={s === speed}
                      onClick={() => onSpeed(s)}
                    >
                      {s}×
                    </button>
                  ))}
                </div>
              )}
            </>
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
