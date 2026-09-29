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
   Library Management → Library): beets' leftover database backups (`library.db-before-*.bak`),
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
3. **New releases** (Library Management): recent (1 to 12 months) and upcoming releases of
   every album artist that the library does not have, from their MusicBrainz discographies
   refreshed daily by a background job (progress shown on the page).

### 6. Apps and listening

1. ✅ **Info endpoints**: `getArtistInfo` (folder ids), `getAlbumInfo`/`getAlbumInfo2` (Last.fm
   album notes, cached), `getSimilarSongs`/`getSimilarSongs2` ("instant mix": the artist and
   its similar artists of the library, else its genre), `includeNotPresent` in
   `getArtistInfo2`. Image URLs are not given (they would need unauthenticated links;
   apps get artist pictures through `coverArt`).
2. ✅ **Lyrics**: `.lrc` files, the files' tags, then LRCLIB (cached in the data folder);
   `getLyrics`, `getLyricsBySongId` (OpenSubsonic `songLyrics`); in the web UI a "Now
   playing" view (player bar button or cover) with synced lyrics following the song
   (click a line to jump there) and a frequency visualizer; a small visualizer can also
   show in the player bar.
3. **Import page**: "Analyzing…" while the "In library" badges are computed; results
   kept a day (data folder) unless the folders or the library change.
4. ✅ **Podcasts and audiobooks** (spec: [docs/specs/podcasts-audiobooks.md](docs/specs/podcasts-audiobooks.md)):
   their own optional folders (Settings → Library, Docker `/podcasts`, `/audiobooks`) and
   admin switches, never mixed with music; Podcasts / Audiobooks pages (continue listening,
   progress, resume, start over); "Import as" Music / Podcast / Audiobook; bookmarks
   (`getBookmarks`, `createBookmark`, `deleteBookmark`); Subsonic apps get both through the
   podcast API (`getPodcasts`, `getNewestPodcasts`, `getPodcastEpisode`; no RSS); player
   speed 1×–2× and −15 s / +30 s for these files, no shuffle / repeat / crossfade. Chapters
   inside a file (M4B / M4A chapter lists, ID3 `CHAP`) listed under it and in Now playing,
   "previous" / "next" by chapter; books whose track numbers are inconsistent are ordered by
   file name; "Dismiss" in Continue listening; deletion in Library Management → Delete.
   Imports go through the review (spec: [docs/specs/spoken-import-review.md](docs/specs/spoken-import-review.md)):
   one card per book / show, metadata prefilled from tags and folder names, candidates from
   Audible, MusicBrainz (chapter titles from the matching edition's tracks), Open Library
   and iTunes, then `<Author>/<Title>/NN - Chapter` (podcasts
   `<Show>/<date> - Episode`), tags rewritten, cover saved.
5. ✅ **Keyboard shortcuts** (web player): Space plays / pauses, ← / → go 10 s back /
   forward, except while typing (text fields, lists), on focused buttons (Space) and
   sliders or menus (arrows).

## Maybe later

- **Equalizer** (web UI only): 10 bands on the Web Audio graph of the visualizer.
- **Moved / renamed files keep their user data** (play counts, stars, playlists): today a
  moved file is a new song (ARCHITECTURE.md 9.5).
- **Split multiple artists** packed in one tag ("A, B", "A feat. B"); beets already puts
  compilations under `Compilations/`.
- Avatars (`getAvatar`).
- Reorganize the library to beets' path formats; upload music to the import folder from
  the web UI.

## Not planned

- **On-the-fly transcoding** (`stream?format=&maxBitRate=`): lossless files are converted
  to MP3 at import time instead.
- **Album download** (zip) in the web UI.
- **Taking over the previous beets database** (`music.db`): Sound-Barrier maintains its
  own beets database (adopt library albums from Library Management → Library).
- **Backups** of the database and secret key: handled on the server side.
- Podcasts, internet radio, shares, jukebox, video.
