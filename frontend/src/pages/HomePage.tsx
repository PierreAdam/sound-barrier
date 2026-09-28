import { useState } from "react";

import type { AlbumID3 } from "../api/types";
import { useSubsonic } from "../api/useSubsonic";
import { AlbumCard } from "../components/AlbumCard";
import { RefreshIcon } from "../components/Icons";
import { plural } from "../format";

type ListType = "random" | "newest" | "frequent" | "recent";

const LISTS: { id: ListType; label: string; empty: string }[] = [
  { id: "random", label: "Random", empty: "The library is empty." },
  { id: "newest", label: "Recently added", empty: "The library is empty." },
  { id: "frequent", label: "Most played", empty: "Play some music: your most played albums will show up here." },
  { id: "recent", label: "Recently played", empty: "Play some music: the albums you listened to will show up here." },
];

const LIST_SIZE = 30;
const STORAGE_KEY = "sound-barrier.home-list";

function savedList(): ListType {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return LISTS.some((l) => l.id === value) ? (value as ListType) : "random";
  } catch {
    return "random";
  }
}

function formatDate(value?: string): string {
  return value ? new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" }) : "";
}

/** The information line under each album, depending on the list. */
function info(list: ListType, album: AlbumID3): string {
  const artist = album.displayArtist ?? album.artist ?? "";
  const detail =
    list === "newest"
      ? formatDate(album.created)
      : list === "frequent"
        ? plural(album.playCount ?? 0, "play")
        : list === "recent"
          ? formatDate(album.played)
          : "";
  return [artist, detail].filter(Boolean).join(" · ");
}

export function HomePage() {
  const [list, setList] = useState<ListType>(savedList);
  const { data, error, loading, reload } = useSubsonic("getAlbumList2", { type: list, size: LIST_SIZE });
  const albums = data?.albumList2.album ?? [];
  const current = LISTS.find((l) => l.id === list) ?? LISTS[0]!;

  function choose(next: ListType) {
    setList(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // remembered for this visit only
    }
  }

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">Home</h1>
        {list === "random" && (
          <button className="button button--ghost" type="button" onClick={reload} disabled={loading}>
            <RefreshIcon /> Shuffle again
          </button>
        )}
      </div>
      <nav className="tabs" role="tablist" aria-label="Album lists">
        {LISTS.map((l) => (
          <button
            key={l.id}
            type="button"
            role="tab"
            aria-selected={list === l.id}
            className={`tabs__tab${list === l.id ? " tabs__tab--active" : ""}`}
            onClick={() => choose(l.id)}
          >
            {l.label}
          </button>
        ))}
      </nav>
      {error && <p className="text-error">{error.message}</p>}
      {loading && !data && <p className="text-muted">Loading…</p>}
      {data && !albums.length && <p className="text-muted">{current.empty}</p>}
      <ul className="album-grid">
        {albums.map((album) => (
          <li key={album.id}>
            <AlbumCard album={album} info={info(list, album)} />
          </li>
        ))}
      </ul>
    </div>
  );
}
