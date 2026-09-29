# Spec: podcasts and audiobooks

Status: agreed (2026-09-29).

Podcasts and audiobooks are separate from music: their own folders on disk, their own
entries in the top menu, never mixed with music in the web UI or in Subsonic's music
endpoints. Subsonic apps get both through the **podcast API** (the formats are close: a
show or a book is a series of long episodes / chapters).

## 1. Folders and settings

- Library folders have a **kind**: `music`, `podcasts`, `audiobooks` (`music_folder.kind`).
  Settings → Library: the music folder as today, plus an optional **Podcasts folder** and
  an optional **Audiobooks folder**.
- Each kind has an admin **switch** (on / off, off by default). Off: its menu entry, its
  import choice and its Subsonic channels are gone; its files and folder stay.
- Docker: two more mount points, `/podcasts` and `/audiobooks`, applied at the first start
  like the music folder (`INITIAL_PODCASTS_DIR`, `INITIAL_AUDIOBOOKS_DIR`).
- The scanner reads every folder the same way (tags, covers, durations). The kind of the
  folder is the type: there is no detection by tags.
- Layout: podcasts `<Show>/<episodes>`; audiobooks `<Author>/<Book>/<chapters>` or
  `<Author> - <Book>/<chapters>` (the tags give author and title anyway). A show / a book
  is an album of the scanner; an episode / a chapter is a song.

## 2. Music stays music

Only music folders are "visible" to the music side: Home, Browse, the artist index, search,
random and play lists, artist and album pages, Missing albums, New releases, the import
"In library" check, and every Subsonic music endpoint (`getMusicFolders` included).

## 3. Import

The Import tab has one button per kind, **Import selected as [Music] [Audiobook] [Podcast]**
(the kinds that are on): the kind is chosen with the click. Folders that look like
audiobooks / podcasts (names such as "Audiobook", "Unabridged", "Podcast"; M4B files; genre
tags) get a badge and that button highlighted; importing them as another kind asks first
(`GET /api/manage/browse/kinds`, library_manager/kind_hints.py).

- Music: beets + MusicBrainz, as today.
- Podcast / Audiobook: reviewed one book / show at a time, then placed into the folder of
  that kind, one folder each, files renamed and retagged (no beets, no conversion): see
  [spoken-import-review.md](spoken-import-review.md). A choice whose folder is not set, or
  whose switch is off, is not offered.

## 4. Web UI

- Top menu: **Podcasts** and **Audiobooks** (when on).
- Each page: **Continue listening** (started, not finished: progress, **Resume**), then the
  grid of shows / books (audiobooks: with their author).
- A show page: episodes newest first (release date in the tags, else the file date), each
  with its progress / "played". A book page: chapters in order (disc, track), the book's
  progress ("Chapter 4 of 12 · 1 h 12 min left"), **Resume** and **Start from the
  beginning**.
- Resuming: the bookmarks of the previous change, now for podcast and audiobook folders
  only (their songs have `mediaType` `podcast` / `audiobook`).
- Player, for these tracks: **speed** 1× to 2× (1, 1.25, 1.5, 1.75, 2; saved per user,
  for spoken audio only), **−15 s / +30 s** buttons. No lyrics.

## 5. Subsonic apps: the podcast API

- `getPodcasts` (`includeEpisodes`, `id`): every show and every book (of the kinds that
  are on) is a channel: id, title, description (tags), cover, status `completed`; its
  episodes: id, `streamId` (the song, for `stream`), `channelId`, title, description,
  `publishDate`, status `completed`, and the song fields (duration, size...). Podcast
  episodes newest first, audiobook chapters in order.
- `getNewestPodcasts` (`count`), `getPodcastEpisode` (OpenSubsonic).
- `stream`, `getCoverArt`, bookmarks work for these songs.
- RSS subscriptions are out of scope: `createPodcastChannel`, `refreshPodcasts`,
  `deletePodcastChannel`, `deletePodcastEpisode`, `downloadPodcastEpisode` answer "not
  supported".

## 6. Out of scope

- RSS subscriptions (feeds, downloads).
- Moving files between kinds from the web UI.
