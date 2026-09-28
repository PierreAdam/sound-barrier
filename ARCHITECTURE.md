# Sound-Barrier — Architecture

Self-hosted music streaming server, meant to replace an existing Subsonic instance.
Any client compatible with Subsonic / Airsonic / Navidrome must work unchanged.

**First goal:** implement the [Subsonic API](http://www.subsonic.org/pages/api.jsp) (v1.16.1)
server-side, with [OpenSubsonic](https://opensubsonic.netlify.app/) extensions where cheap.
**Web UI:** React + Vite single-page app in `frontend/`, using the Subsonic API (`/rest`).
**Library management:** integrated beets (import, tagging, covers) driven from the web UI
through our own endpoints under `/api` (sections 8–9). Target: one Docker container.

---

## 1. Technology stack

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| Web framework | FastAPI + uvicorn |
| Validation / response models | Pydantic v2 |
| Database | PostgreSQL 16+ (extensions: `pg_trgm`, `unaccent`; `pgvector` later) |
| DB access | SQLAlchemy 2 (async) + asyncpg |
| Migrations | Alembic |
| Audio tags | mutagen |
| Images (cover art) | Pillow |
| Transcoding (later) | ffmpeg subprocess |
| Dependency management | uv |
| Lint / format / types | ruff, pyright (strict) |
| Tests | pytest, pytest-asyncio, httpx, Testcontainers (Postgres) |
| Local environment | docker-compose (Postgres + optional Navidrome as reference server) |

---

## 2. High-level architecture

```
 Subsonic clients ──► /rest/*  (Subsonic adapter: u/t/s auth, XML|JSON envelope)
                                   │
 Web UI (later)   ──► /api/*   (native adapter: JWT, REST, OpenAPI)
                                   │
                          ┌────────▼─────────┐
                          │  services layer   │   ← all business logic lives here
                          └────────┬─────────┘
                                   │
                ┌──────────────────┼───────────────────┐
                ▼                  ▼                   ▼
           PostgreSQL        music files on disk   artwork cache on disk
                ▲
                │
           scanner (walks library, reads tags, upserts rows)
```

Rules:
- **Adapters are thin.** `/rest` and `/api` only parse input, call services, and map
  results to their own wire format. No SQL, no business rules in adapters.
- **Services return domain objects**, never Subsonic- or UI-specific DTOs.
- **The scanner is the only writer** of library tables (`song`, `album`, `artist`, …).
  User-data tables (stars, ratings, playlists…) are written by services.

---

## 3. Project layout

```
sound-barrier/
├── ARCHITECTURE.md
├── docker-compose.yml        # development services (Postgres)
├── Dockerfile                # application image (backend + web UI)
├── docker/                   # production compose file, .env example, entrypoint
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/                  # migrations
│   ├── app/
│   │   ├── main.py               # FastAPI app factory, mounts /rest and /api
│   │   ├── core/                 # settings, db session, crypto, logging
│   │   ├── models/               # SQLAlchemy ORM tables
│   │   ├── services/             # library, browsing, search, playlists, annotations,
│   │   │                         # streaming, artwork, users, play queue…
│   │   ├── scanner/              # file walker, tag reader (mutagen), upsert logic
│   │   ├── subsonic/
│   │   │   ├── auth.py           # u/p/t/s/apiKey → current user
│   │   │   ├── envelope.py       # subsonic-response wrapper, XML + JSON serializers
│   │   │   ├── errors.py         # SubsonicError(code, message) → HTTP 200 + status=failed
│   │   │   ├── schemas.py        # Child, AlbumID3, ArtistID3, Playlist… (Pydantic)
│   │   │   └── endpoints/        # system, browsing, lists, search, media, playlists,
│   │   │                         # annotation, user, queue, bookmarks
│   │   └── api/                  # native API for the web UI (empty for now)
│   └── tests/
└── frontend/                     # React + Vite SPA (see frontend/README.md)
```

---

## 4. Subsonic API conventions

- **Routes:** `/rest/{method}` and `/rest/{method}.view`, both **GET and POST**
  (POST params may be form-encoded).
- **Common params:** `u` (user), `v` (client API version), `c` (client name), `f` (format).
- **Format:** `f=xml` (default!), `f=json`, `f=jsonp` (+ `callback`). One response model,
  two serializers. Binary endpoints (`stream`, `download`, `getCoverArt`, `getAvatar`)
  return raw bytes and use the envelope only on error.
- **Authentication**, in order of precedence:
  1. `apiKey` (OpenSubsonic): hashed key lookup.
  2. `t` + `s`: `t == md5(password + s)` → requires the password to be **recoverable**
     (stored encrypted with a server-side key, never hashed).
  3. `p`: plaintext or `enc:<hex>`.
- **Errors:** HTTP 200, `status="failed"`, `error{code, message}`.
  Codes: 0 generic, 10 missing param, 20/30 client/server version mismatch,
  40 wrong credentials, 41 token auth not supported, 42/43/44 (OpenSubsonic auth),
  50 not authorized, 60 trial expired, 70 not found.
- **Envelope attributes:** `status`, `version="1.16.1"`, plus OpenSubsonic
  `type="sound-barrier"`, `serverVersion`, `openSubsonic=true`.
- **IDs are opaque strings** on the wire. Music folder IDs are integers (per spec).
- **`stream`** must support HTTP `Range` / `206 Partial Content` (seeking).
- **`getCoverArt`** accepts the `coverArt` value we emit, but should also tolerate
  album / song / artist IDs (some clients send those).

---

## 5. Database schema

Conventions:
- Primary keys: `uuid` (`gen_random_uuid()`), except `music_folder.id` (integer, required
  by the spec) and append-only logs (`bigint identity`).
- Timestamps: `timestamptz`. Durations: milliseconds (`integer`), exposed as seconds.
- Library rows are **soft-deleted** (`missing_since`) when their file disappears, so user
  data (stars, ratings, playlists) survives a temporarily unmounted disk or a move.
  Rows are purged after a configurable grace period.
- `created_at` on library rows = **date added to the library**. It must stay stable across
  rescans (it drives `getAlbumList2?type=newest`).
- Search columns (`*_search`) are lowercase + unaccented strings computed by the scanner,
  indexed with `pg_trgm` GIN indexes.

### 5.1 Library (written by the scanner)

#### `music_folder`: configured library roots
| Column | Type | Notes |
|---|---|---|
| id | integer PK | exposed as `musicFolderId` |
| name | text | |
| path | text unique | absolute path on disk |
| created_at | timestamptz | |

#### `directory`: filesystem folders (for folder-based browsing)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| music_folder_id | int FK → music_folder | |
| parent_id | uuid FK → directory, null | null = the music folder root (path `""`, named after the folder) |
| path | text | relative to music folder; unique with `music_folder_id` |
| name | text | |
| artwork_id | uuid FK → artwork, null | folder image, if any |
| mtime | timestamptz | used for incremental scans |
| created_at, updated_at, missing_since | timestamptz | |

#### `artist`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| match_key | text unique | scanner identity: `mbz:<id>` or `name:<normalized>` |
| name | text | |
| sort_name | text | from tags, or name with ignored articles stripped |
| name_search | text | normalized for search |
| mbz_artist_id | text null | MusicBrainz ID |
| artwork_id | uuid FK → artwork, null | artist image |
| album_count | int | denormalized, recomputed after scan |
| created_at, updated_at, missing_since | timestamptz | |

Matching key during scan (`match_key`): `mbz_artist_id` if present, else normalized name.

#### `album`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| match_key | text unique | scanner identity (see below) |
| name | text | |
| sort_name, name_search | text | |
| artist_id | uuid FK → artist | primary album artist (Subsonic `artistId`) |
| display_artist | text | full credited string, e.g. "A feat. B" |
| year | smallint null | |
| release_date | text null | partial ISO date (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`) |
| original_release_date | text null | |
| is_compilation | boolean | |
| release_types | text[] | album, ep, single, live… |
| record_labels | text[] | |
| moods | text[] | |
| explicit_status | text null | `explicit` / `clean` / null |
| disc_titles | jsonb | `[{disc: 1, title: "…"}]` |
| mbz_album_id, mbz_release_group_id | text null | |
| artwork_id | uuid FK → artwork, null | |
| song_count | int | denormalized |
| duration_ms | bigint | denormalized |
| created_at, updated_at, missing_since | timestamptz | |

Matching key during scan (`match_key`): `mbz:<mbz_album_id>` if present, else
`<normalized album artist>|<normalized album name>`. Untagged files use the directory name as
album name. Compilations without an album artist get "Various Artists".

#### `song`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| music_folder_id | int FK → music_folder | |
| directory_id | uuid FK → directory | Subsonic `parent` |
| album_id | uuid FK → album | |
| artist_id | uuid FK → artist | primary track artist |
| path | text | relative to music folder; unique with `music_folder_id` |
| title, sort_title, title_search | text | |
| display_artist | text | |
| display_composer | text null | |
| track_number | smallint null | |
| disc_number | smallint null | |
| year | smallint null | |
| duration_ms | int | |
| bit_rate | int | kbps |
| sample_rate | int null | Hz |
| bit_depth | smallint null | |
| channels | smallint null | |
| size | bigint | bytes |
| suffix | text | `mp3`, `flac`… |
| content_type | text | MIME type |
| bpm | smallint null | |
| comment | text null | |
| explicit_status | text null | |
| replaygain_track_gain, replaygain_track_peak | real null | |
| replaygain_album_gain, replaygain_album_peak | real null | |
| mbz_recording_id, mbz_track_id | text null | |
| artwork_id | uuid FK → artwork, null | embedded art, falls back to album art |
| file_mtime | timestamptz | skip unchanged files on rescan |
| created_at, updated_at, missing_since | timestamptz | |

Indexes: `(album_id, disc_number, track_number)`, `artist_id`, `directory_id`,
GIN trigram on `title_search`.

#### `genre`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | text unique | |

#### Junction tables (multi-valued tags, OpenSubsonic `artists[]`, `genres[]`, contributors)
| Table | Columns |
|---|---|
| `song_artist` | song_id, artist_id, role (`artist`, `albumartist`, `composer`, `performer`, …), sub_role null, position |
| `album_artist` | album_id, artist_id, role, position |
| `song_genre` | song_id, genre_id, position |
| `album_genre` | album_id, genre_id, position |

The first genre by `position` is the single `genre` field exposed to legacy clients.

#### `artwork`: cover images
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | exposed as `coverArt` |
| source | text | `embedded` (inside an audio file) or `file` (cover.jpg…) |
| path | text | audio file or image file, relative to music folder |
| music_folder_id | int FK | |
| mtime | timestamptz | invalidates the resized-image cache |
| width, height | int null | |

Resized variants (`size` param) are cached on disk, not in the DB.

#### `lyrics` (phase 2: `getLyrics`, `getLyricsBySongId`)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| song_id | uuid FK → song | |
| lang | text | ISO 639 or `xxx` |
| synced | boolean | |
| offset_ms | int | |
| lines | jsonb | `[{start_ms, value}]` |
| source | text | `embedded` / `lrc` file |

### 5.2 Users and access

#### `app_user`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| username | text unique | |
| password_enc | bytea | **encrypted** (Fernet, server key) because token auth needs the plaintext |
| email | text null | |
| max_bit_rate | int | 0 = unlimited |
| scrobbling_enabled | boolean | |
| is_admin | boolean | `adminRole` |
| settings_role, download_role, upload_role, playlist_role, cover_art_role, comment_role, podcast_role, stream_role, jukebox_role, share_role, video_conversion_role | boolean | Subsonic roles |
| avatar_path | text null | |
| created_at, updated_at, last_seen_at | timestamptz | |

On first start, when the table is empty, the server creates `admin` / `admin` (admin role)
and warns at every start while that default password is unchanged.

#### `user_music_folder`: which libraries a user can see (no rows = all folders)
| Column | Type |
|---|---|
| user_id | uuid FK → app_user |
| music_folder_id | int FK → music_folder |

#### `api_key` (OpenSubsonic `apiKey`, later also for the web UI)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK → app_user | |
| name | text | |
| key_hash | text unique | SHA-256 of the key; the key itself is never stored |
| created_at, last_used_at | timestamptz | |

### 5.3 Per-user data

#### Annotations: stars, ratings, play counts
One table per item type, so foreign keys and cascades stay real:
`song_annotation`, `album_annotation`, `artist_annotation`, `directory_annotation`.

| Column | Type | Notes |
|---|---|---|
| user_id | uuid FK → app_user | PK part 1 |
| item_id | uuid FK → song / album / artist / directory | PK part 2 |
| starred_at | timestamptz null | null = not starred |
| rating | smallint null | 1–5, null = unrated |
| play_count | int | default 0 |
| last_played_at | timestamptz null | |

`averageRating` is computed from these rows (`avg(rating)`) at query time.
Album and artist play counts are derived from song scrobbles.

#### `playlist`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| owner_id | uuid FK → app_user | |
| name | text | |
| comment | text null | |
| is_public | boolean | |
| song_count | int | denormalized |
| duration_ms | bigint | denormalized |
| created_at, changed_at | timestamptz | |

#### `playlist_entry`
| Column | Type | Notes |
|---|---|---|
| playlist_id | uuid FK → playlist | PK part 1 |
| position | int | PK part 2, 0-based |
| song_id | uuid FK → song | duplicates allowed |

#### `playlist_allowed_user` (Subsonic `allowedUser`)
| Column | Type |
|---|---|
| playlist_id | uuid FK → playlist |
| user_id | uuid FK → app_user |

#### `web_play_queue` (web UI, `GET/PUT /api/queue`)

The web UI's queue, one per user and shared by all their browsers, like the original
Subsonic web player: opening the web UI anywhere brings it back (paused, at the saved
position). Kept apart from the Subsonic clients' queue below: the two never mix.

| Table | Fields |
|---|---|
| `web_play_queue` | user_id PK, song_ids uuid[] (play order, no FK: songs gone are dropped when read), original_order int[] null (shuffled: play positions in the original order), current_index, position_ms, revision (+1 per save), updated_at |

Saved by the web UI (`useWebQueue`) about 1 s after a change, every 20 s while playing,
on pause, and when the page closes (only if that tab has unsaved changes or is playing, so
a tab left open with an old queue cannot overwrite a newer one). A tab coming back to the
foreground, not playing, takes a newer queue saved by another computer.

#### `play_queue` / `play_queue_entry` (`getPlayQueue`, `savePlayQueue`)
| Table | Columns |
|---|---|
| `play_queue` | user_id PK, current_song_id null, position_ms, changed_at, changed_by (client name) |
| `play_queue_entry` | user_id, position (PK together), song_id |

#### `bookmark`
| Column | Type |
|---|---|
| user_id, song_id | PK |
| position_ms | bigint |
| comment | text null |
| created_at, changed_at | timestamptz |

#### `play_history`: every scrobble (append-only)
| Column | Type | Notes |
|---|---|---|
| id | bigint identity PK | |
| user_id | uuid FK | |
| song_id | uuid FK | |
| played_at | timestamptz | |
| client | text | `c` param |
| submission | boolean | true = counted play, false = "now playing" notification |

Drives `getAlbumList2?type=recent|frequent`, and later stats and recommendations.
A `submission=true` scrobble also bumps `song_annotation.play_count` / `last_played_at`.

#### `now_playing` (`getNowPlaying`)
| Column | Type | Notes |
|---|---|---|
| user_id, client | PK | one entry per user and player |
| song_id | uuid FK | |
| updated_at | timestamptz | entries older than the song duration + margin are ignored |

Kept in the DB (not in memory) so it works with several uvicorn workers.

### 5.4 System

#### `scan`: library scan runs (`startScan`, `getScanStatus`)
| Column | Type |
|---|---|
| id | bigint identity PK |
| kind | text (`full` / `quick`) |
| status | text (`running` / `done` / `failed`) |
| started_at, finished_at | timestamptz |
| files_seen, added, updated, removed | int |
| error | text null |

#### `server_setting`: key/value
| Column | Type | Notes |
|---|---|---|
| key | text PK | e.g. `ignored_articles`, `purge_missing_after_days` |
| value | jsonb | |

### 5.5 Deliberately out of scope for now
Podcasts, internet radio, shares, jukebox, chat, video, per-player transcoding profiles.
Their endpoints will return empty lists or error 0 / 50 until needed.

---

## 6. Scanner

Code: `app/scanner/` (`walker.py` filesystem, `tags.py` metadata, `scanner.py` orchestration).

1. Take a Postgres advisory lock: one scan at a time, across the server and the CLI.
2. For each `music_folder`: if the folder is not accessible (unmounted disk), **skip it**
   rather than marking everything missing. Otherwise walk the tree (in a thread).
3. Upsert every directory; its artwork is the first of `cover.*`, `folder.*`, `front.*`,
   `album.*`, `albumart.*`.
4. For each audio file: quick scan skips it if `(size, mtime)` is unchanged; full scan re-reads
   everything. Tags are read by a thread pool (mutagen), 100 files per transaction.
   ID3, Vorbis comments, MP4 and APEv2 are mapped onto one set of canonical keys first.
5. Upsert `artist` → `album` → `song`, then replace the song's `song_artist` (roles: artist,
   albumartist, composer, lyricist, performer…) and `song_genre` rows. Artists without a
   MusicBrainz ID reuse an MBID-identified artist with the same name.
6. Songs and directories not seen get `missing_since = now()`; seen again, it is cleared
   (same row, so user data survives). Orphan artwork rows are deleted.
7. Recompute derived data in SQL for the whole library: album counters and cover (folder
   image of its first track, else first embedded picture), album genres, artist album
   counts, missing albums / artists.
8. Progress (phase, files read / to read) and totals are stored in `scan`, read by
   `getScanStatus` and by the settings page (`GET /api/scan`).

**Targeted scans** (`kind = "targeted"`, `run_scan(targets={folder id: [dirs]})`, started
with `ScanManager.scan_paths`): only the given sub-directories are walked, plus their
parents (own files only), and only those paths can be marked missing; derived data is
still recomputed for the whole library. Used after an import (the album folders, before
the task shows "imported") and after a deletion (the folders of the deleted files, before
the API answers), so the web UI can reload its lists (side menu, Browse) right away.
`scan_paths` waits for a scan already running, and falls back to a quick scan if the
targeted one cannot run.

Scans run: from the CLI (`sound-barrier scan [--full]`), from `startScan` or the settings
page (admins), at server startup, and daily at a time set in Settings (default 02:00,
server local time; `TZ` in Docker). The schedule is stored in `server_setting`
(`scan_schedule`); `SOUND_BARRIER_SCHEDULER=false` disables automatic scans.

Known limits (to address later): moved/renamed files are seen as new songs (user data on the
old path is not carried over); multi-artist values packed in one string ("A, B") are not split.

---

## 7. Implementation roadmap (Subsonic API)

| Phase | Endpoints | Outcome |
|---|---|---|
| **1: connect and play** | `ping`, `getLicense`, `getMusicFolders`, `getArtists`, `getArtist`, `getAlbum`, `getSong`, `stream`, `getCoverArt`, `getOpenSubsonicExtensions` | Client connects, browses by tags, plays music |
| **2: daily use** | `getAlbumList2`, `getRandomSongs`, `search3`, `getGenres`, `getSongsByGenre`, `getStarred2`, `star`, `unstar`, `setRating`, `scrobble`, `getNowPlaying`, playlists (`get/create/update/deletePlaylist`), `getUser`, `getScanStatus`, `startScan` | Full personal use |
| **3: folder browsing and extras** | `getIndexes`, `getMusicDirectory`, `getAlbumList`, `getStarred`, `search2`, `getPlayQueue`, `savePlayQueue`, bookmarks, `getLyrics`, `getLyricsBySongId`, `download`, `getAvatar`, user management | Compatibility with folder-based clients |

Implemented beyond phase 1: search (`search2`, `search3`; an empty query lists everything by pages), folder browsing (`getIndexes`, `getMusicDirectory`, `getAlbumList`: the directories of the music folders, albums given as the directory of their first song), stars and ratings (`star`, `unstar`, `setRating`, `getStarred`, `getStarred2`; folder ids stand for their album or artist), `getRandomSongs`, `getGenres`, `getSongsByGenre`, `getNowPlaying`, playlists (`getPlaylists`, `getPlaylist`, `createPlaylist`, `updatePlaylist`, `deletePlaylist`), the apps' play queue (`getPlayQueue`, `savePlayQueue`, `getPlayQueueByIndex`, `savePlayQueueByIndex`). Not planned: transcoding (lossless files are converted at import). Also done ahead of their phase: `getArtistInfo2` and `getTopSongs` (Last.fm, library songs only), `getAlbumList2` (all list types; `newest` uses the date an album's files were written, never moving forward when they are re-tagged) and `scrobble` (play counts and last played per user for songs, albums and artists, play history, now playing; the web player reports a play after half the track or 4 minutes, tracks of 30 s or more).
| **4: transcoding** | `stream?format=&maxBitRate=`, `getTranscodeDecision` (OpenSubsonic) | ffmpeg on-the-fly |

Before phase 1: record the real traffic between the client and the current Subsonic
server (logging proxy) to confirm which endpoints and params it actually uses.

---

## 8. Native API (`/api`)

Our own endpoints, for everything the Subsonic API does not cover (library management,
settings, jobs). Used only by our web UI; Subsonic clients never see it.

- JSON REST, described by FastAPI's OpenAPI schema.
- **Auth:** `POST /api/auth/login` (username + password) opens a server-side session and
  sets an `HttpOnly`, `SameSite=Strict` cookie. The web UI logs in once and gets both the
  Subsonic token (for `/rest`) and the session cookie (for `/api`).
- Admin-only routes for anything that writes files or changes settings.

Table `web_session`: id, user_id, token_hash (sha256 of the cookie; the token itself is
never stored), created_at, expires_at (12 h, or 30 days with "remember me"), last_seen_at.

| Route | Who | Purpose |
|---|---|---|
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | anyone / signed in | session |
| `PUT /api/auth/password` | signed in | own password; other sessions are closed, this one kept |
| `GET/PUT /api/preferences` | any user | the caller's web UI preferences, stored in `app_user.preferences` (JSONB): theme (`mode` dark / light / system, `accent` palette), player crossfade (on/off, seconds) and the "Missing albums" categories (`discography.categories`, default `["album"]`). Volume, shuffle and repeat stay in each browser |
| `GET/PUT /api/queue`, `GET /api/queue/revision` | any user | the caller's web queue (songs in the Subsonic `Child` format, original order when shuffled, current index, position); the revision tells whether another browser changed it |
| `GET/PUT /api/external/settings` | admin | Last.fm API key (checked with Last.fm, stored encrypted with the secret key, never sent back) fanart.tv API key (same), the artist picture source (`none`, `deezer`, `fanarttv`; providers in `app/external/pictures.py`; album cover sources in `app/external/covers.py`: Deezer, and fanart.tv and the Cover Art Archive for albums with a MusicBrainz release group id), and MusicBrainz lookups on/off (`musicbrainz`) |
| `GET /api/artists/{id}/info`, `POST .../info/refresh` (admin) | any user | biography, similar artists (linked when in the library), top songs of the library, picture credit; cached 30 days in `artist_info` (1 day after a failure), picture file in `<data>/artist-pictures/`, served by `getCoverArt` (artist id or `ar-<id>-<version>`) |
| `GET /api/artists/{id}/discography`, `POST .../discography/refresh` (admin) | any user | "Missing albums" (`services/discography.py`, spec in `docs/specs/missing-albums.md`): the artist's release groups on MusicBrainz (`release-group-status=website-default`, one request per second server-wide), each with its category (`album`, `album+live`...) and the library album it is (by release group id, release id, then title); cached 7 days in `artist_info` |
| `GET /api/manage/new-releases?months=`, `POST /api/manage/new-releases/sync` | admin | New releases (`services/new_releases.py`): recent and upcoming release groups of all album artists that the library does not have, from the cached discographies (24 h). `sync` starts `DiscographySync`, a background job refreshing the old ones one artist at a time (MusicBrainz' rate), not tied to the request; GET reports its progress |
| `GET /api/artists/{id}/musicbrainz/candidates?q=`, `PUT /api/artists/{id}/musicbrainz` | admin | link the artist to a MusicBrainz artist (search results or an id / URL); stored in `artist_info.mbz_artist_id_override`, wins over the tags and the automatic search |
| `GET /api/artists/{id}/discography/covers/{mbid}` | any user | cover of a release group, found automatically (Cover Art Archive, fanart.tv, Deezer) and kept in `<data>/discography-covers/` (no cover: retried after 30 days) |
| `GET /api/plugins`, `PUT /api/plugins/{id}`, `POST /api/plugins/{id}/try`, `GET /api/plugins/{id}/assets/{name}` | admin | embedded plugins (`app/plugins/`, spec in `docs/specs/album-sources.md`): each declares its settings fields (rendered generically in Settings → Album search) and capabilities (`links`); settings in `server_setting` under `plugin:<id>`, files in `<data>/plugins/<id>/`. First plugin: "Search links" (GET / POST URL templates, icons fetched from public addresses only) |
| `GET /api/artists/{id}/discography/{mbid}/links` | admin | the enabled plugins' links for a release group of the artist's discography (the "Missing albums" popup; POST links are submitted by the browser) |
| `GET /api/albums/{id}/cover-search?q=`, `GET /api/covers/thumbnail?url=`, `POST /api/albums/{id}/cover` | admin | album cover choice: search the cover sources (`app/external/covers.py`, Deezer for now; images only downloaded from each source's declared hosts), preview through the server, apply = `cover.jpg` written in the album's folders (previous one kept as `cover.previous.<ext>`) then a targeted scan. `getCoverArt` answers with an ETag and `no-cache`, so a changed cover shows at once |
| `GET/PUT /api/albums/{id}/tags` | admin | tag editor: album fields (album, album artist, year, genre, compilation) and track fields (disc, number, title, artist); only changed fields are written, through beets for the files it knows (its database follows), then a targeted scan; returns the album's id afterwards (it changes when its name or artist does). A new year clears the month and day |
| `POST /api/manage/cleanup` | admin | the daily cleanup now (`services/maintenance.py`): beets migration backups, beets entries without file, old import staging folders, resized covers older than 60 days, unused artist pictures |
| `GET /api/library/revision` | any user | id of the last finished scan; the web UI polls it (every 10 s while the tab is visible, `useLibraryWatcher`) and reloads its cached lists when it changes |
| `GET/PUT /api/library` | admin | the library folder (single folder in the UI; changing the path keeps the folder id, then a quick scan starts) |
| `GET /api/scan`, `POST /api/scan` | admin | detailed scan status (phase, files read / to read, totals, next run), start a scan |
| `GET/PUT /api/scan/schedule` | admin | daily scan time, on/off, scan at startup |

User management uses the Subsonic endpoints (`getUsers`, `createUser`, `updateUser`,
`deleteUser`, `changePassword`) since Subsonic covers it. Two roles: **admin** and
**user**; Subsonic's role flags are derived from them (`services/users.apply_role`).
Safety rules: no deleting yourself, no removing your own admin role, always one admin.

---

## 9. Library management (integrated beets)

Sound-Barrier replaces the `beet` command: all music management happens in the web UI.
[beets](https://beets.io) is used **as a Python library** inside the backend, never
through its CLI. Users never edit a beets config file.

### 9.0 What exists today (Manage Library page, admins)

Code: `backend/app/library_manager/`, API `backend/app/api/manage.py`, UI
`frontend/src/pages/ManageLibraryPage.tsx` + `pages/manage/`.

- **Tagger abstraction** (`tagger.py`): `identify(items)`, `search(items, artist, album,
  release_id)`, `apply(items, candidate | None, library_root, options)`, `forget(paths)`,
  plus `supports_matching`. Candidates carry a match distance, release details and a
  track-by-track mapping; a recommendation (strong / medium / low / none) comes with them.
  Everything else (jobs, review, API, UI) only uses this interface.
- **`BeetsTagger`** (`beets_tagger.py`, beets 2.14 used as a library, the default):
  `identify` / `search` call beets' matcher (`tag_album`, MusicBrainz plugin; search by
  artist + album, or a release id / MusicBrainz URL). `apply` runs a real beets import
  session on the album whose answers are the decision taken in the UI (the chosen
  candidate, re-fetched by id, or as-is): beets writes the tags, copies the files to its
  path formats, runs fetchart / embedart and records the album in its database
  (`/beets/library.db`). Configuration: defaults equal to the previous beets setup
  (`$albumartist/$album%aunique{}/$track - $title`, plugins musicbrainz, fetchart,
  embedart), then `/beets/config.yaml` if present, then what Sound-Barrier controls
  (library directory, copy / move, no prompts, not threaded). All calls come from the
  import manager's single tagger thread (beets has global state).
- **`AsIsTagger`** (`as_is.py`): no matching; imports with the current tags into
  `<album artist>/<album>/<track> - <title>.<ext>`. Used when beets is not installed or
  `SOUND_BARRIER_TAGGER=as-is` (the integration tests).
- **Duplicates** (`duplicates.py`): before applying, the album is looked up in
  Sound-Barrier's own tables (same MusicBrainz release, or same album artist + name,
  ignoring case), which know the whole library; beets' database only knows what beets
  imported. beets' own duplicate check is kept too.
- **Import folders**: set by admins in the page (`server_setting` `import_settings`, with
  copy mode and auto-apply of strong matches). Only these folders can be browsed or
  imported from; every path from the UI is checked on its real path (`files.ensure_within`).
- **Workflow** (`imports.py`): `import_job` (one "Import" click) -> `import_task` (one per
  folder containing audio files) -> identify -> strong match + auto-apply: imported,
  otherwise `pending` for review (apply a candidate, import as-is, search, skip, retry).
  One worker, one tagger thread; a quick scan is requested after each import. Tasks that
  cannot be applied for a fixable reason (e.g. already in the library) go back to
  `pending` with the reason.
- **Delete** (`deletion.py`): permanent. Song files are deleted (only inside their music
  folder), then folders left with only sidecar files (covers, .nfo, .cue...) and empty
  parents; then song rows (stars, playlist entries...), albums and artists left without
  songs; `tagger.forget()` is called.

| Route | Purpose |
|---|---|
| `GET/PUT /api/manage/settings` | import folders, auto-apply, tagger name / matching support |
| `GET /api/manage/browse?path=` | list an import folder (no path: the import folders) |
| `POST /api/manage/imports`, `GET /api/manage/imports` | start an import, recent jobs + tasks |
| `POST /api/manage/tasks/{id}/decision` | `apply` (+ candidateId), `as_is`, `skip`, `retry` |
| `POST /api/manage/tasks/{id}/search` | artist / album or release id (needs matching) |
| `POST /api/manage/delete` | album ids and / or song ids, permanent |
| `GET /api/manage/library-status` | library counts against the tagger's database (beets): songs / albums it knows, entries whose file is gone, album folders it does not know |
| `POST /api/manage/adopt` | album folders of the library (relative paths) to add to beets: an import job of kind `adopt` (matched like an import, unclear matches in Review, tags written in place, files never moved; no duplicate check, no conversion) |
| `POST /api/manage/forget-missing` | removes from beets' database the entries whose file no longer exists |

### 9.1 Principles

- **Files are the contract.** beets writes tags and copies/moves files; our scanner
  reads the result into Postgres, which remains the only source for serving music.
- **beets keeps a private SQLite library** in `/data/beets/library.db` (duplicate
  detection, MusicBrainz re-sync). It is an internal detail: it can always be rebuilt
  from the files ("adopt library" below).
- **beets runs in a background worker process**, never in a web request: it is
  synchronous, uses SQLite and calls MusicBrainz (rate limited to 1 request/second).
  Jobs and their state live in Postgres; the UI polls them (like the scan status).
- **Admin only**, with a preview before anything is written, and a log per job.

### 9.2 Settings (UI → beets config)

Stored in `server_setting`, turned into beets' configuration in code at worker start.
Defaults come from the current setup:

| Setting | Default | beets option |
|---|---|---|
| Library folder | `/music` (mount) | `directory` |
| Import mode | copy (source left in the inbox) | `import.copy` / `import.move` |
| Write tags to files | yes | `import.write` |
| Remove source from inbox after import | no | (ours) |
| Path templates | `$albumartist/$album%aunique{}/$track - $title` · singletons `Single/$artist/$title` · compilations `Compilations/$album%aunique{}/$track - $artist - $title` | `paths` |
| Plugins | `musicbrainz`, `fetchart`, `embedart` | `plugins` |
| Auto-apply strong matches | yes (only doubtful albums wait for review) | (ours, uses beets' recommendation level) |

### 9.3 Import inbox (replaces `beet import`)

New music is dropped into the **inbox** mount (later: uploaded from the browser).
Import is split in two non-blocking steps, so no beets pipeline ever waits for a user:

1. **Analyze** (job): a custom beets `ImportSession` walks the inbox, groups files into
   albums, and for each album stores the MusicBrainz candidates (album, artist, year,
   label, country, media, track count, match distance, track-by-track differences,
   duplicate check) in `import_task`, then skips it. Nothing is written.
2. **Review** (UI): for each album the admin picks a candidate, searches MusicBrainz
   (artist/album or release ID/URL), imports as-is, imports as singletons, or skips.
   Duplicate handling: keep both, replace the old one, skip.
3. **Apply** (job): a new `ImportSession` per decided album, restricted to the chosen
   release (`search_ids`), runs beets' normal pipeline: tags, path templates,
   copy/move, and plugins (`fetchart`, `embedart`) exactly as `beet import` would.
   Then a targeted scan of the new album directory makes it appear in the library.

New tables:

| Table | Columns |
|---|---|
| `job` | id, kind (`import_analyze`, `import_apply`, `mbsync`, `fetchart`, `adopt`…), status (`queued`, `running`, `done`, `failed`, `cancelled`), created_by, params jsonb, progress jsonb, log text, created_at, started_at, finished_at |
| `import_task` | id, job_id, source_path, status (`pending_review`, `decided`, `applying`, `imported`, `skipped`, `failed`), items jsonb (files + current tags), candidates jsonb, duplicates jsonb, decision jsonb, result_album_id, error |

### 9.4 Existing library and maintenance

- **Adopt library** (one-time job): registers the files already in `/music` in beets'
  library without re-tagging them (equivalent of `beet import -A -C`). The tags already
  contain MusicBrainz IDs, so re-sync keeps working. The old `music.db` is not reused
  (its paths point to the old server layout).
- **Album actions** (later): refresh from MusicBrainz (`mbsync`), fetch / embed cover,
  change match (re-import in place), edit tags, delete (with confirmation).
- **Reorganize** (later): apply changed path templates to the whole library, with a
  preview of the moves.

### 9.5 Moved files keep their user data

beets moves and renames files, and our scanner currently sees a moved file as a new
song. Two complementary fixes, required before beets can move files:

- moves done by our jobs are known (beets `item_moved` event): the job updates
  `song.path` / `directory_id` directly, so the row (and its stars, ratings, playlist
  entries) is kept;
- moves done outside the app: the scanner matches a new file to a song that just went
  missing by MusicBrainz track ID, else by (size, duration, title, album).

### 9.6 Packaging

- beets is an optional extra (`pip install sound-barrier[beets]`); the feature is hidden
  when it is not installed.
- The worker is started by `sound-barrier serve` as a child process (one container),
  or separately with `sound-barrier worker`.

---

## 10. Deployment (Docker) ✅

One application image (`Dockerfile` at the root, multi-stage: the web UI is built with
Node, then a `python:3.13-slim` image with the backend and ffmpeg). FastAPI serves the
built web UI at `/` (`app/web.py`: static files, `index.html` for client-side routes;
unknown `/rest` and `/api` paths stay 404), the Subsonic API at `/rest` and our API at
`/api`: one port (4040), no reverse proxy needed inside the container. PostgreSQL runs as
a separate container (`docker/docker-compose.yml`, settings in `docker/.env`).

| Mount | Purpose | Access |
|---|---|---|
| `/music` | the library | read-write (imports, deletion) |
| `/import` | import root folder (e.g. the downloads folder) | read-only is enough: imports copy |
| `/beets` | beets configuration and library (for the future beets tagger) | read-write |
| `/data` | application data: secret key, artwork cache, import staging | read-write |

- On first start, `/music` becomes the library folder and `/import` the import root
  (`SOUND_BARRIER_INITIAL_LIBRARY_DIR` / `_IMPORT_DIR`); only while nothing is configured,
  so what is changed later in Settings is kept.
- `docker/entrypoint.sh`: generates the secret key into `/data/secret.key` unless
  `SOUND_BARRIER_SECRET_KEY` is given, applies the migrations (retrying while Postgres
  starts), then runs `sound-barrier serve`.
- Runs as an unprivileged user (`user: PUID:PGID` in compose, the owner of the music).
- `TZ` sets the time zone of the scan schedule; `FORWARDED_ALLOW_IPS` lets uvicorn trust a
  reverse proxy (HTTPS detection for the session cookie).

---|---|---|
| `/music` | the library | read-write |
| `/inbox` | new music waiting for import | read-write |
| `/data` | application data: artwork cache, beets config and library, job logs | read-write |

Sign-in throttling: `SOUND_BARRIER_LOGIN_MAX_FAILURES` (10) failures from one IP address within `SOUND_BARRIER_LOGIN_BLOCK_MINUTES` (15) refuse that address for as long (web sign-in and Subsonic API, `app/core/throttle.py`, in memory).

Configuration through environment variables (`SOUND_BARRIER_*`); secrets such as
`SOUND_BARRIER_SECRET_KEY` are passed at runtime, never baked into the image.

---

## 11. Overall roadmap

What is left, in order, and what was decided against: [ROADMAP.md](ROADMAP.md).

| Step | Content |
|---|---|
| A. Play music ✅ | `getArtist`, `getAlbum`, `getSong`, `stream` (range requests), `download`, `getCoverArt` (resized, cached); artist and album pages; player with queue, shuffle, repeat, crossfade |
| B. Foundations | `/api` with web sessions, job table + worker process, targeted scans, move detection (9.5), settings storage |
| C. Import inbox ✅ | analyze / review / apply with beets + MusicBrainz (9.3), settings page (9.2), adopt library (9.4, Manage Library → Library) |
| D. Packaging ✅ | Dockerfile, production compose file, web UI served by FastAPI |
| E. Maintenance | album actions, reorganize, tag editor, upload to inbox |
| F. Subsonic phases 2–4 | daily-use endpoints, folder browsing, transcoding (section 7) |

---

## 12. Testing strategy

- Unit tests: tag parsing, auth (token/salt, `enc:`), XML/JSON envelope, error mapping.
- Integration tests: FastAPI `httpx.AsyncClient` against Postgres (Testcontainers)
  with a small fixture library of tagged audio files.
- Compatibility tests: golden responses captured from Navidrome on the same fixture
  library, compared field by field (ignoring IDs and timestamps).
