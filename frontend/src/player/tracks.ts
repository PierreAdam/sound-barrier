import type { Child } from "../api/types";
import type { Track } from "./engine";

/** A song from the Subsonic API as a player track. */
export function songToTrack(song: Child): Track {
  return {
    id: song.id,
    title: song.title,
    artist: song.displayArtist ?? song.artist,
    album: song.album,
    albumId: song.albumId,
    artistId: song.artistId,
    coverArt: song.coverArt,
    durationSeconds: song.duration,
    year: song.year,
    suffix: song.suffix,
    size: song.size,
    bitRate: song.bitRate,
    longForm: song.mediaType === "audiobook" || song.mediaType === "podcast",
    spokenKind: song.mediaType === "audiobook" ? "audiobooks" : song.mediaType === "podcast" ? "podcasts" : undefined,
    chapters: song.chapters?.map((c) => ({ start: c.startMs / 1000, title: c.title })),
  };
}

/** The page of a track's album: the album, or the podcast / audiobook. */
export function albumUrl(track: Track): string | undefined {
  if (!track.albumId) return undefined;
  return track.spokenKind ? `/${track.spokenKind}/${track.albumId}` : `/albums/${track.albumId}`;
}

/** The page of a track's artist (music only: authors have none). */
export function artistUrl(track: Track): string | undefined {
  return track.artistId && !track.longForm ? `/artists/${track.artistId}` : undefined;
}
