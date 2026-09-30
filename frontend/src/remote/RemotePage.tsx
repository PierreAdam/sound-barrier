import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { CoverArt } from "../components/CoverArt";
import {
  CrossfadeIcon,
  NextIcon,
  PauseAtEndIcon,
  PauseIcon,
  PlayIcon,
  PreviousIcon,
  RemoteIcon,
  RemoveIcon,
  RepeatIcon,
  ShuffleIcon,
  VolumeIcon,
} from "../components/Icons";
import { REPEAT_LABELS, SPEEDS } from "../components/PlayerBar";
import { formatTime, plural } from "../format";
import type { RemoteCommand, RemoteState, RemoteTargetInfo } from "./protocol";
import { RemoteSocket } from "./socket";

/** A target, with when its state arrived here (its position advances from then). */
interface Target extends RemoteTargetInfo {
  at: number;
}

/** Where the target's track is now: its reported position, advanced while it plays. */
function positionOf(state: RemoteState, at: number, now: number): number {
  const position = state.playing ? state.position + ((now - at) / 1000) * state.rate : state.position;
  return state.duration > 0 ? Math.min(position, state.duration) : position;
}

/**
 * Remote control (menu under the username): the whole screen becomes a remote for one
 * of the user's players with remote control on (from its queue panel). The player bar's
 * controls, sent to that tab; what it plays is shown as it reports it.
 */
export function RemotePage() {
  const navigate = useNavigate();
  const [targets, setTargets] = useState<Target[] | null>(null); // null: not connected yet
  const [connected, setConnected] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const socket = useRef<RemoteSocket | null>(null);

  useEffect(() => {
    const remote = new RemoteSocket({
      open: () => remote.send({ type: "remote" }),
      message: (message) => {
        const now = Date.now();
        if (message.type === "targets") {
          setTargets(message.targets.map((target) => ({ ...target, at: now })));
        } else if (message.type === "state") {
          setTargets(
            (previous) =>
              previous?.map((target) =>
                target.id === message.target ? { ...target, state: message.state, at: now } : target,
              ) ?? previous,
          );
        } else if (message.type === "error") {
          setError(message.message);
        }
      },
      connected: setConnected,
    });
    socket.current = remote;
    remote.start();
    return () => {
      remote.stop();
      socket.current = null;
    };
  }, []);

  // One player only: straight to it. The selected one gone (tab closed...): the list.
  const target = targets?.find((t) => t.id === selected) ?? (targets?.length === 1 ? targets[0] : undefined);
  useEffect(() => {
    if (selected && targets && !targets.some((t) => t.id === selected)) setSelected(null);
  }, [selected, targets]);

  const send = (command: RemoteCommand) => {
    if (!target) return;
    setError(null);
    socket.current?.send({ type: "command", target: target.id, command });
  };
  const close = () => (window.history.length > 1 ? navigate(-1) : navigate("/home"));

  return (
    <div className="remote" role="dialog" aria-modal="true" aria-label="Remote control">
      <header className="remote__header">
        {target && (targets?.length ?? 0) > 1 ? (
          <button className="button button--ghost" type="button" onClick={() => setSelected(null)}>
            ‹ Players
          </button>
        ) : (
          <span className="remote__brand">
            <RemoteIcon /> Remote control
          </span>
        )}
        <span className={`remote__connection${connected ? " remote__connection--on" : ""}`}>
          {connected ? "Connected" : "Connecting…"}
        </span>
        <button className="icon-button" type="button" aria-label="Close the remote control" onClick={close}>
          <RemoveIcon />
        </button>
      </header>

      {error && <p className="remote__error text-error">{error}</p>}

      {target ? (
        <RemoteControls target={target} send={send} />
      ) : (
        <TargetList targets={targets} onSelect={setSelected} />
      )}
    </div>
  );
}

function TargetList({ targets, onSelect }: { targets: Target[] | null; onSelect(id: string): void }) {
  if (targets === null) return <p className="remote__empty text-muted">Looking for your players…</p>;
  if (targets.length === 0) {
    return (
      <div className="remote__empty">
        <p>No player can be controlled right now.</p>
        <p className="text-muted">
          On the computer (or tab) that should play, open the queue above the player bar and turn on “Remote control”.
          It appears here at once.
        </p>
      </div>
    );
  }
  return (
    <ul className="remote__targets">
      {targets.map((target) => (
        <li key={target.id}>
          <button className="remote__target" type="button" onClick={() => onSelect(target.id)}>
            <CoverArt id={target.state?.track?.coverArt ?? undefined} size={56} className="remote__target-cover" />
            <span className="remote__target-text">
              <span className="remote__target-name">{target.playerName}</span>
              <span className="text-muted">{target.device}</span>
              <span className="remote__target-track">
                {target.state?.track
                  ? `${target.state.playing ? "Playing" : "Paused"}: ${target.state.track.title}`
                  : "Nothing playing"}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function RemoteControls({ target, send }: { target: Target; send(command: RemoteCommand): void }) {
  const state = target.state;
  const [now, setNow] = useState(() => Date.now());
  const [seeking, setSeeking] = useState<number | null>(null); // the seek bar, while dragged
  const playing = state?.playing ?? false;

  // The position moves on its own while playing.
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [playing]);

  if (!state) return <p className="remote__empty text-muted">Waiting for {target.playerName}…</p>;
  const { track } = state;
  const position = seeking ?? positionOf(state, target.at, Math.max(now, target.at));
  const disabled = track === null;
  const commitSeek = () => {
    if (seeking !== null) send({ name: "seek", position: seeking });
    setSeeking(null);
  };
  const nextSpeed = SPEEDS[(SPEEDS.indexOf(state.speed) + 1) % SPEEDS.length] ?? 1;

  return (
    <div className="remote__controls">
      <p className="remote__playing-on text-muted">
        Playing on <strong>{target.playerName}</strong> · {target.device}
      </p>
      <CoverArt id={track?.coverArt ?? undefined} size={320} className="remote__cover" alt="" />
      <div className="remote__track">
        <h1 className="remote__title">{track?.title ?? "Nothing playing"}</h1>
        {track && (
          <p className="remote__artist text-muted">
            {[track.chapter, track.artist, track.album].filter(Boolean).join(" · ")}
          </p>
        )}
        {state.count > 0 && (
          <p className="remote__position text-muted">
            {state.index >= 0 ? `Track ${state.index + 1} of ${state.count}` : plural(state.count, "track")}
          </p>
        )}
      </div>

      <div className="remote__seek">
        <input
          className="slider"
          type="range"
          aria-label="Seek"
          min={0}
          max={state.duration || 0}
          step={1}
          value={Math.floor(position)}
          disabled={disabled || !state.duration}
          onChange={(e) => setSeeking(Number(e.target.value))}
          onPointerUp={commitSeek}
          onKeyUp={commitSeek}
          onBlur={commitSeek}
        />
        <div className="remote__times text-muted">
          <span>{formatTime(position)}</span>
          <span>{formatTime(state.duration)}</span>
        </div>
      </div>

      <div className="remote__transport">
        {!state.spoken && (
          <button
            className={`icon-button remote__side${state.shuffle ? " icon-button--active" : ""}`}
            type="button"
            aria-label="Shuffle"
            aria-pressed={state.shuffle}
            onClick={() => send({ name: "shuffle" })}
          >
            <ShuffleIcon />
          </button>
        )}
        <button
          className="icon-button remote__button"
          type="button"
          aria-label={state.chapters ? "Previous chapter" : "Previous"}
          disabled={disabled}
          onClick={() => send({ name: "previous" })}
        >
          <PreviousIcon />
        </button>
        {state.spoken && (
          <button className="icon-button remote__skip" type="button" aria-label="15 seconds back" onClick={() => send({ name: "skip", seconds: -15 })}>
            −15
          </button>
        )}
        <button
          className="remote__play"
          type="button"
          aria-label={playing ? "Pause" : "Play"}
          disabled={disabled}
          onClick={() => send({ name: "toggle" })}
        >
          {playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        {state.spoken && (
          <button className="icon-button remote__skip" type="button" aria-label="30 seconds forward" onClick={() => send({ name: "skip", seconds: 30 })}>
            +30
          </button>
        )}
        <button
          className="icon-button remote__button"
          type="button"
          aria-label={state.chapters ? "Next chapter" : "Next"}
          disabled={disabled || !state.hasNext}
          onClick={() => send({ name: "next" })}
        >
          <NextIcon />
        </button>
        {!state.spoken && (
          <button
            className={`icon-button remote__side${state.repeat !== "off" ? " icon-button--active" : ""}`}
            type="button"
            aria-label={REPEAT_LABELS[state.repeat]}
            title={REPEAT_LABELS[state.repeat]}
            onClick={() => send({ name: "repeat" })}
          >
            <RepeatIcon one={state.repeat === "one"} />
          </button>
        )}
      </div>

      <div className="remote__extras">
        {state.spoken ? (
          <>
            <button
              className={`button remote__option${state.pauseAtEnd ? " remote__option--on" : ""}`}
              type="button"
              aria-pressed={state.pauseAtEnd}
              onClick={() => send({ name: "pauseAtEnd" })}
            >
              <PauseAtEndIcon /> {state.pauseAtEndLabel}
            </button>
            <button
              className="button remote__option"
              type="button"
              aria-label={`Playback speed: ${state.speed}×`}
              onClick={() => send({ name: "speed", value: nextSpeed })}
            >
              {state.speed}×
            </button>
          </>
        ) : (
          <button
            className={`button remote__option${state.crossfade ? " remote__option--on" : ""}`}
            type="button"
            aria-pressed={state.crossfade}
            onClick={() => send({ name: "crossfade" })}
          >
            <CrossfadeIcon /> Crossfade
          </button>
        )}
      </div>

      <div className="remote__volume">
        <button
          className="icon-button"
          type="button"
          aria-label={state.muted ? "Unmute" : "Mute"}
          onClick={() => send({ name: "mute" })}
        >
          <VolumeIcon muted={state.muted} />
        </button>
        <input
          className="slider"
          type="range"
          aria-label="Volume"
          min={0}
          max={1}
          step={0.02}
          value={state.muted ? 0 : state.volume}
          onChange={(e) => send({ name: "volume", value: Number(e.target.value) })}
        />
      </div>
    </div>
  );
}
