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
  };
}
