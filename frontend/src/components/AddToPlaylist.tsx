import { type FormEvent, useEffect, useRef, useState } from "react";

import { invalidateSubsonicCache, useSubsonic } from "../api/useSubsonic";
import { useSession } from "../auth/AuthContext";
import { plural } from "../format";
import { PlaylistIcon } from "./Icons";

/**
 * A button opening a small menu: add `songIds` to one of the user's playlists, or to a new
 * one. `label` is the button text ("Add to playlist", "Save as playlist"...).
 */
export function AddToPlaylist({
  songIds,
  label = "Add to playlist",
  className = "action-bar__item",
}: {
  songIds: string[];
  label?: string;
  className?: string;
}) {
  const { client, user } = useSession();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const { data } = useSubsonic("getPlaylists");
  const mine = (data?.playlists.playlist ?? []).filter((p) => p.owner === user.username);

  // Closes when clicking elsewhere.
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (menu.current && !menu.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    try {
      await action();
      invalidateSubsonicCache();
      setMessage(done);
      setOpen(false);
      setName("");
      setTimeout(() => setMessage(null), 2500);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function create(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    void run(() => client.call("createPlaylist", { name: trimmed, songId: songIds }), `Saved as “${trimmed}”.`);
  }

  return (
    <div className="playlist-menu" ref={menu}>
      <button className={className} type="button" disabled={!songIds.length} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <PlaylistIcon />
        {label}
      </button>
      {message && !open && <span className="playlist-menu__message">{message}</span>}
      {open && (
        <div className="playlist-menu__panel" role="menu">
          <p className="playlist-menu__hint text-muted">{plural(songIds.length, "song")} to add</p>
          {mine.map((playlist) => (
            <button
              key={playlist.id}
              className="playlist-menu__item"
              type="button"
              role="menuitem"
              disabled={busy}
              onClick={() =>
                void run(
                  () => client.call("updatePlaylist", { playlistId: playlist.id, songIdToAdd: songIds }),
                  `Added to “${playlist.name}”.`,
                )
              }
            >
              <span>{playlist.name}</span>
              <span className="text-muted">{playlist.songCount}</span>
            </button>
          ))}
          <form className="playlist-menu__new" onSubmit={create}>
            <input
              className="field__input"
              placeholder="New playlist"
              aria-label="New playlist name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <button className="button button--primary" type="submit" disabled={busy || !name.trim()}>
              Create
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
