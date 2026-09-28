# Spec: artist action bar and missing albums

Status: implemented (2026-09-28). Roadmap entry: [ROADMAP.md](../../ROADMAP.md) §5.

On the artist page, an action bar (like the album page's) sits between the artist header and
the album grid. Besides playback actions, it opens a **Missing albums** view: the artist's
discography from MusicBrainz, compared with the library.

## 1. Artist action bar (`frontend/src/pages/ArtistPage.tsx`)

- A `nav.action-bar` (same markup and classes as `AlbumPage`), between `.artist-header`
  and `.album-grid`, with four items:
  1. **Play all**
  2. **Add to queue**
  3. **Play next**
  4. **Missing albums**
- The three playback actions take every song of the artist's albums shown on the page, in
  album order (year), then disc, then track. They reuse `engine.add` / `engine.playNext`.
- **Missing albums** is a toggle (`action-bar__item--active` when on). The view is kept in
  the URL (`/artists/:id?view=missing`) so back navigation and links work.

## 2. Missing albums view

### Categories

MusicBrainz gives every release group one **primary type** (Album, Single, EP, Broadcast,
Other) and zero or more **secondary types** (Compilation, Soundtrack, Spokenword,
Interview, Audiobook, Audio drama, Live, Remix, DJ-mix, Mixtape/Street, Demo, Field
recording). As on the MusicBrainz artist page, a **category** is the exact combination:
"Album", "Album + Compilation", "Album + Live", "EP + Demo", "Single"…

- The category bar lists the combinations present for this artist, one checkbox each, with
  a count "missing / total", plus **All** and **None** shortcuts.
- Order: Album, then its combinations, then EP, Single, Broadcast, Other (primary types in
  MusicBrainz order, then secondary types alphabetically).
- **Default: only `album`** (Album with no secondary type) is checked. Any other combination,
  including one seen for the first time, starts unchecked: a user who does not want live
  albums never sees them unless they enable them.
- The selection is saved **per user, for all artists**, in the user preferences
  (`/api/preferences`, e.g. `discographyCategories: ["album"]`). No localStorage.

### Content

- One section per checked category, headed like the MusicBrainz page, each a grid of cards
  sorted by first release date.
- A card shows the cover, title and year.
  - **Owned** album: its library cover, a clear "In library" overlay, links to our album page.
  - **Missing** album: the cover found as in §5 (placeholder otherwise), links to the
    release group on MusicBrainz.
  - A first release date in the future gets an "Upcoming" badge.
- States: loading; MusicBrainz unavailable (cached error, retry); artist not linked to
  MusicBrainz (§4); nothing missing in the checked categories.

## 3. Discography data (backend)

- New client `backend/app/external/musicbrainz.py`, on the shared `httpx` client
  (`app.state.http`).
- Discography: `GET https://musicbrainz.org/ws/2/release-group?artist={mbid}&release-group-status=website-default&fmt=json&limit=100&offset=…`
  - `website-default` returns the same release groups as the MusicBrainz website overview
    (it leaves out those whose releases are all promotional, bootleg or pseudo-releases).
  - No `type=` filter: the whole discography is stored, filtering is done in the UI.
  - Pages are capped (about 5, i.e. 500 release groups).
  - Kept per release group: `id`, `title`, `primary-type`, `secondary-types`,
    `first-release-date`.
- **Rate limit**: at most one request per second to musicbrainz.org, enforced in-process
  (nothing throttles outbound requests today).
- **User-Agent**: MusicBrainz requires a meaningful one; ours gains a contact URL
  (`Sound-Barrier/<version> (+<project URL>)`).
- **Category key**: primary type then sorted secondary types, lowercased and joined with
  `+` (`album`, `album+live`, `album+compilation+live`); no primary type → `other`.
- **Cache**: new columns on `artist_info` (Alembic migration): `discography` (JSONB),
  `discography_mbid`, `discography_fetched_at`, `discography_error`. Refreshed after 7 days,
  retried one day after a failure (the existing `_stale` logic).
- **Matching with the library**, computed on every request (not cached), so a newly
  scanned album shows as owned right away. For each library album of the artist, in order:
  1. `Album.mbz_release_group_id` equals the release group id;
  2. `Album.mbz_album_id` (release id) resolved to its release group
     (`/ws/2/release/{id}?inc=release-groups`, cached);
  3. normalized title, ignoring edition suffixes ("(Deluxe Edition)", "[Remastered 2011]",
     "Expanded"…).

## 4. Linking the artist to MusicBrainz

The MusicBrainz artist id used, in order of priority:

1. **Manual override** (always wins);
2. the id from the file tags (`Artist.mbz_artist_id`);
3. **automatic search** by name (`/ws/2/artist?query=artist:"<name>"`), accepted only for
   an exact normalized name match with score 100 and no other result at 100.

Without a confident match, the view shows:

- **Candidates**: the top 5 search results (name, disambiguation, country, active years,
  type); choosing one links the artist.
- **Manual entry**: a MusicBrainz artist id or a `musicbrainz.org/artist/…` URL, checked
  with `/ws/2/artist/{mbid}` and confirmed by showing the name found.

Linking, changing ("Change MusicBrainz artist") or clearing the link is **admin only** (it
changes data shared by all users). The override is stored in `artist_info`
(`mbz_artist_id_override`), not on `Artist`: the scanner stays the only writer of library
tables. Creating a missing artist on MusicBrainz is out of scope.

## 5. Covers of missing albums

- Resolved automatically, first hit wins, through `COVER_PROVIDERS`:
  1. **Cover Art Archive** by release group id
     (`https://coverartarchive.org/release-group/{id}/front-500`), exact and keyless;
  2. **fanart.tv** by release group id, when a key is configured;
  3. **Deezer**, by artist and title with the existing name matching.
- The Cover Art Archive becomes a regular `CoverProvider`, so it is also offered in the
  album page's cover search (next to Deezer and fanart.tv) when the album has a release
  group id.
- Lazy endpoint `GET /api/artists/{id}/discography/covers/{rgMbid}` (only release groups
  of that artist's discography): the first request resolves and downloads the cover to
  `<data_dir>/discography-covers/<rgMbid>.<ext>`; later ones are served from disk. A miss
  is recorded (`<rgMbid>.none`) and retried after 30 days.
- The frontend loads them with `loading="lazy"`, placeholder while missing.

## 6. API (`/api` only, client in `frontend/src/api/native.ts`)

| Method and path | Who | Purpose |
|---|---|---|
| `GET /api/artists/{id}/discography` | any user | Discography with library matches (below) |
| `POST /api/artists/{id}/discography/refresh` | admin | Fetch again from MusicBrainz |
| `GET /api/artists/{id}/musicbrainz/candidates` | admin | Search results for §4 |
| `PUT /api/artists/{id}/musicbrainz` | admin | `{ mbid }` sets the override, `{ mbid: null }` clears it |
| `GET /api/artists/{id}/discography/covers/{rgMbid}` | any user | Cover image of a release group |

`GET /api/artists/{id}/discography` returns:

```json
{
  "artistMbid": "…",
  "mbidSource": "manual | tags | search | null",
  "fetchedAt": "…",
  "error": null,
  "releaseGroups": [
    {
      "mbid": "…",
      "title": "Versus the World",
      "category": "album",
      "primaryType": "Album",
      "secondaryTypes": [],
      "firstReleaseDate": "2002-11-18",
      "upcoming": false,
      "owned": { "albumId": "…" }
    }
  ]
}
```

## 7. Settings

- An "Enable MusicBrainz lookups" switch in Settings → External services
  (`ExternalServices` model, `ExternalSection.tsx`), on by default; no key needed.
  Off: the "Missing albums" item is hidden and nothing is sent to MusicBrainz.

## 8. Out of scope

- Downloading or importing missing albums.
- Hiding individual release groups ("not interested").
- Missing tracks inside owned albums.
- Creating artists on MusicBrainz.
- Anything on the Subsonic side (no equivalent endpoint).
