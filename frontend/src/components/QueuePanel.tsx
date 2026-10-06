import { type DragEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { formatTime, formatSize, plural } from "../format";
import { usePlayer } from "../player/PlayerContext";
import { AddToPlaylist } from "./AddToPlaylist";
import { PlayIcon, RemoveIcon, ShuffleIcon, TrashIcon, UndoIcon } from "./Icons";
import { PlaybackMenu } from "./PlaybackMenu";

interface DragState {
  from: number;
  over: number | null;
  after: boolean; // drop below the hovered row rather than above
}

/** The play queue, shown above the player bar: reorder, remove, undo, clear. */
export function QueuePanel({ open, onClose }: { open: boolean; onClose(): void }) {
  const { state, engine } = usePlayer();
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [drag, setDrag] = useState<DragState | null>(null);
  const currentRow = useRef<HTMLTableRowElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const { queue, keys } = state;

  // Show the playing track when the panel opens.
  // Scrolls the track list only: scrollIntoView would also scroll the (overflow: hidden) slot
  // clipping the panel while it is still below the player bar, making it jump during the
  // opening animation.
  useEffect(() => {
    const body = bodyRef.current;
    const row = currentRow.current;
    if (!open || !body || !row) return;
    const bodyRect = body.getBoundingClientRect();
    const rowRect = row.getBoundingClientRect();
    if (rowRect.top < bodyRect.top) body.scrollTop += rowRect.top - bodyRect.top;
    else if (rowRect.bottom > bodyRect.bottom) body.scrollTop += rowRect.bottom - bodyRect.bottom;
  }, [open]);

  // Forget selected entries that left the queue.
  useEffect(() => {
    setSelected((previous) => {
      const next = new Set([...previous].filter((key) => keys.includes(key)));
      return next.size === previous.size ? previous : next;
    });
  }, [keys]);

  const totalSeconds = queue.reduce((sum, track) => sum + (track.durationSeconds ?? 0), 0);
  const allSelected = queue.length > 0 && selected.size === queue.length;

  function toggle(key: number) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function removeSelected() {
    engine.remove(keys.flatMap((key, position) => (selected.has(key) ? [position] : [])));
  }

  function onDragOver(event: DragEvent<HTMLTableRowElement>, position: number) {
    if (!drag) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const rect = event.currentTarget.getBoundingClientRect();
    const after = event.clientY > rect.top + rect.height / 2;
    if (drag.over !== position || drag.after !== after) setDrag({ ...drag, over: position, after });
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    if (drag && drag.over !== null) {
      let to = drag.over + (drag.after ? 1 : 0);
      if (drag.from < to) to -= 1; // the dragged row leaves its old place first
      engine.move(drag.from, to);
    }
    setDrag(null);
  }

  return (
    <section className={`queue${open ? " queue--open" : ""}`} aria-label="Queue" inert={!open}>
      <header className="queue__header">
        <h2 className="queue__title">Queue</h2>
        <PlaybackMenu open={open} onNavigate={onClose} />
        <nav className="action-bar" aria-label="Queue actions">
          <button className="action-bar__item" type="button" onClick={() => engine.clear()} disabled={!queue.length}>
            <TrashIcon />
            Clear
          </button>
          <button className="action-bar__item" type="button" onClick={() => engine.undo()} disabled={!state.canUndo}>
            <UndoIcon />
            Undo
          </button>
          {/* Not for audiobooks and podcasts. */}
          {!state.spoken && (
            <button
              className={`action-bar__item${state.shuffle ? " action-bar__item--active" : ""}`}
              type="button"
              aria-pressed={state.shuffle}
              onClick={() => engine.toggleShuffle()}
            >
              <ShuffleIcon />
              Shuffle
            </button>
          )}
          <button
            className="action-bar__item queue__remove-selected"
            type="button"
            onClick={removeSelected}
            disabled={!selected.size}
          >
            <RemoveIcon />
            Remove selected
          </button>
          <AddToPlaylist songIds={queue.map((t) => t.id)} label="Save as playlist" />
        </nav>
        <span className="queue__summary">
          {plural(queue.length, "track")} • {formatTime(totalSeconds)}
        </span>
        <button className="icon-button" type="button" aria-label="Close queue" onClick={onClose}>
          <RemoveIcon />
        </button>
      </header>

      <div className="queue__body" ref={bodyRef}>
        {queue.length === 0 ? (
          <p className="queue__empty text-muted">The queue is empty. Play or add songs from an album.</p>
        ) : (
          <table className="tracks queue__tracks">
            <thead>
              <tr>
                <th className="queue__col-remove" aria-label="Remove" />
                <th className="tracks__select">
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={allSelected}
                    onChange={() => setSelected(allSelected ? new Set() : new Set(keys))}
                  />
                </th>
                <th>Title</th>
                <th>Album</th>
                <th>Artist</th>
                <th className="tracks__duration" aria-label="Duration">
                  ⏱
                </th>
                <th className="queue__col-year">Year</th>
                <th className="queue__col-format">Format</th>
                <th className="queue__col-size">Size</th>
                <th className="queue__col-bitrate">Bitrate</th>
              </tr>
            </thead>
            <tbody onDrop={onDrop}>
              {queue.map((track, position) => {
                const key = keys[position] ?? position;
                const current = position === state.index;
                const dropClass =
                  drag && drag.over === position && drag.from !== position
                    ? drag.after
                      ? " queue__row--drop-after"
                      : " queue__row--drop-before"
                    : "";
                return (
                  <tr
                    key={key}
                    ref={current ? currentRow : undefined}
                    className={`tracks__row queue__row${current ? " tracks__row--current" : ""}${
                      drag?.from === position ? " queue__row--dragging" : ""
                    }${dropClass}`}
                    draggable
                    onDragStart={(event) => {
                      event.dataTransfer.effectAllowed = "move";
                      event.dataTransfer.setData("text/plain", track.title); // required by Firefox
                      setDrag({ from: position, over: null, after: false });
                    }}
                    onDragOver={(event) => onDragOver(event, position)}
                    onDragEnd={() => setDrag(null)}
                    onDoubleClick={() => engine.playAt(position)}
                  >
                    <td className="queue__col-remove">
                      <button
                        className="icon-button tracks__action"
                        type="button"
                        title="Remove from queue"
                        aria-label={`Remove ${track.title} from queue`}
                        onClick={() => engine.remove([position])}
                      >
                        <RemoveIcon />
                      </button>
                    </td>
                    <td className="tracks__select">
                      <input
                        type="checkbox"
                        aria-label={`Select ${track.title}`}
                        checked={selected.has(key)}
                        onChange={() => toggle(key)}
                      />
                    </td>
                    <td className="tracks__title">
                      <button
                        className="queue__play"
                        type="button"
                        title="Play"
                        onClick={() => engine.playAt(position)}
                      >
                        {current && <PlayIcon />}
                        {track.title}
                      </button>
                    </td>
                    <td>{track.albumId ? <Link to={`/albums/${track.albumId}`}>{track.album}</Link> : track.album}</td>
                    <td>
                      {track.artistId ? <Link to={`/artists/${track.artistId}`}>{track.artist}</Link> : track.artist}
                    </td>
                    <td className="tracks__duration">{formatTime(track.durationSeconds)}</td>
                    <td className="queue__col-year">{track.year ?? ""}</td>
                    <td className="queue__col-format">{track.suffix ?? ""}</td>
                    <td className="queue__col-size">{formatSize(track.size)}</td>
                    <td className="queue__col-bitrate">{track.bitRate ? `${track.bitRate} kbps` : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
