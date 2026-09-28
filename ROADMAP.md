# Sound-Barrier roadmap

Decisions taken on what is left to do (2026-09-28). The design of what exists is in
[ARCHITECTURE.md](ARCHITECTURE.md); this file tracks what is planned, in order.

## Done (2026-09-28) and to do

### 1. Subsonic API gaps

1. ✅ **Search**: `search3` (ID3) and `search2` (folders) for the apps; a search field in the
   web UI top bar (left of the user name) with a results page (artists, albums, songs).
2. ✅ **Folder browsing**: `getIndexes`, `getMusicDirectory`, `getAlbumList` (clients such as
   DSub browse by folders).
3. ✅ **Stars, ratings and daily-use endpoints**, API only (no web UI for stars / ratings):
   `star`, `unstar`, `setRating`, `getStarred`, `getStarred2`, `getRandomSongs`,
   `getGenres`, `getSongsByGenre`, `getNowPlaying`.
4. ✅ **The apps' play queue**: `getPlayQueue`, `savePlayQueue`, and the OpenSubsonic
   index-based variants (`indexBasedQueue`) (kept apart from the web
   UI's queue, see ARCHITECTURE.md 5.3).

### 2. Web UI

1. ✅ Remove the album "Download" button.
2. ✅ **Playlists**: the Subsonic endpoints (`getPlaylists`, `getPlaylist`, `createPlaylist`,
   `updatePlaylist`, `deletePlaylist`) and web UI pages; "Save as playlist" from the queue.
3. ✅ **Album track selection**: with tracks ticked, "Add to queue" and "Play next" only take
   those tracks (a small "2 tracks" tag next to the buttons says so).

### 3. Library management

1. ✅ **Tag editor** (admins): album fields and track fields, written into the files (through
   beets for the files it knows, so its database stays in sync), then a targeted scan: the
   web UI and every Subsonic app see the change.
2. ✅ **Embedded covers** (600 × 600): when choosing an album cover, optionally embed it into the audio
   files too (a reasonable resolution, not the full-size image).
3. ✅ **fanart.tv** as a picture source (artist pictures, and album covers when a MusicBrainz
   id is known), with its API key in Settings → External services.

### 4. Security and maintenance

1. ✅ **Login throttling** (10 failures in 15 minutes, configurable): after N failed sign-ins from one IP address (web UI or Subsonic
   API), that address is refused for a while.
2. ✅ **Scheduled cleanups** (10 minutes after start, then daily; "Clean up now" in
   Manage Library → Library): beets' leftover database backups (`library.db-before-*.bak`),
   beets entries whose file is gone, abandoned import staging folders, old cached covers.

### 5. Discography

1. **Artist action bar and missing albums** (spec:
   [docs/specs/missing-albums.md](docs/specs/missing-albums.md)): "Play all", "Add to
   queue", "Play next" and a "Missing albums" view on the artist page, from the artist's
   MusicBrainz discography, filtered by release type combination (only "Album" by default,
   saved in the user preferences).
2. **Plugins and album search links** (spec:
   [docs/specs/album-sources.md](docs/specs/album-sources.md)): embedded plugins with their
   own settings; the first one gives admins search links (GET or POST, icons) for missing
   albums.

## Maybe later

- **Moved / renamed files keep their user data** (play counts, stars, playlists): today a
  moved file is a new song (ARCHITECTURE.md 9.5).
- **Split multiple artists** packed in one tag ("A, B", "A feat. B"); beets already puts
  compilations under `Compilations/`.
- Bookmarks, lyrics (`getLyrics`, `getLyricsBySongId`), avatars (`getAvatar`).
- Reorganize the library to beets' path formats; upload music to the import folder from
  the web UI.

## Not planned

- **On-the-fly transcoding** (`stream?format=&maxBitRate=`): lossless files are converted
  to MP3 at import time instead.
- **Album download** (zip) in the web UI.
- **Taking over the previous beets database** (`music.db`): Sound-Barrier maintains its
  own beets database (adopt library albums from Manage Library → Library).
- **Backups** of the database and secret key: handled on the server side.
- Podcasts, internet radio, shares, jukebox, video.
