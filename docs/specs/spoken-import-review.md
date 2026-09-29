# Spec: reviewing audiobook and podcast imports

Status: agreed (2026-09-29). Extends [podcasts-audiobooks.md](podcasts-audiobooks.md) §3,
which copied the selected folders as they were.

An audiobook or podcast import goes through the **Review** tab, one card per detected
book / show. The admin checks and edits the metadata there (helped by online lookups),
then imports it: the files land in **one folder per book / show**, renamed, with their
tags rewritten. Nothing reaches the library before that.

## 1. Detection: what is a book / a show

- The selected folders are walked like music imports: every folder that directly holds
  audio files is a candidate.
- **Disc-like sub-folders are merged** into their parent: a folder named like `CD1`,
  `CD 02`, `Disc 3`, `Disk 1`, `Part 2`, `Partie 1`, `Teil 3`, `Vol. 2` (a word of that
  list and a number, nothing else) belongs to the book of its parent folder. Every other
  audio folder is its own book / show.
- One import task per book / show (like one per album for music).
- In the review, a book can be **merged into another** waiting book of the same import
  (for splits the rule above missed); its files are appended to that book's chapters.

## 2. Analysis: the proposal

When a task is analyzed, the files are read (tags, durations, embedded pictures,
chapters inside the files) and a proposal is made, which the review shows filled in:

- **Audiobook**: title (album tag, else the folder name without leading numbers and
  noise such as "Unabridged", "Audiobook", brackets), author (album artist, else artist;
  never "Various Artists"; the composer when the compilation flag is set), narrator,
  year, genre ("Audiobook"), and the chapters: the files **in order** (disc / track
  numbers when consistent, else the file names in natural order, see spoken.py), each
  with a title (its title tag, else its file name cleaned).
- **Podcast**: show name, author, genre ("Podcast"), and the episodes, each with a title
  and a date (the date tag, else the file date), newest first.
- **Lookups** (§4) run right away; the best candidate, when it is a clear match, is shown
  first but nothing is applied without the admin.

## 3. The review card

- The metadata form: **Title**, **Author**, **Narrator** (audiobooks), **Series** and
  **Book number** (audiobooks, optional), **Year**, **Genre**, **Description**.
- **Cover**: the folder's image, the embedded one, or a candidate's (preview; the chosen
  one is saved as `cover.jpg` in the book / show folder).
- **Candidates** from the lookups (cover, title, author, narrator, series, year,
  duration against the files' duration). "Use" fills the form with a candidate (the
  admin can still edit), a search box looks up other titles / authors.
- **Chapters / episodes**: the list in the proposed order with editable titles; moved up
  / down (audiobooks); podcasts: editable dates.
- **Where it goes** (preview): `Audiobooks/J.K. Rowling/Harry Potter and the Prisoner of
  Azkaban/03 - The Knight Bus.mp3`.
- Actions: **Import**, **Merge into…** (another waiting book of the same import),
  **Skip**. Failed tasks: **Retry**, like music.

## 4. Lookups (Settings → External services, each with a switch, on by default)

- **Audible** (audiobooks): the catalog search of `api.audible.com` (unofficial, no key),
  by title and author; gives title, subtitle, authors, narrators, series and number,
  release date, runtime, description, cover. Region setting (`com`, `co.uk`, `fr`, `de`,
  `ca`, `com.au`, `it`, `es`, `in`, `co.jp`), default `com`. Editions are ranked by how
  close their runtime is to the files' total duration, then by title.
- **MusicBrainz** (audiobooks, no key; the MusicBrainz switch, shared with Missing albums):
  releases of type "Audiobook", by title and author. The artist credit gives the author(s)
  and the narrator(s) ("J.K. Rowling read by Stephen Fry"). Editions with **as many tracks
  as the files** come first, and for them (the first two) the track list is fetched: their
  track titles (cleaned like file names) can become the chapter titles ("Use chapter
  titles", in the reviewed order), with a warning when the tracks and the files last
  clearly differently. The edition used is written to the tags (release and release group
  ids). Covers from the Cover Art Archive.
- **Open Library** (audiobooks, official, no key): title, authors, first publication
  year, cover. Used as well, listed after Audible's and MusicBrainz's candidates.
- The review shows the best two results of each catalog, all of them on demand. "Use"
  fills what a result knows and keeps the rest of the form: e.g. Audible for the book,
  then MusicBrainz for the chapter titles.
- **iTunes Search** (podcasts, official, no key): show name, author, genre, artwork.
- Lookups are best effort: a service that fails or times out is listed as unavailable on
  the card, the review still works by hand.

## 5. Importing a reviewed book / show

- **Layout**: audiobooks `<Audiobooks folder>/<Author>/<Title>/`, podcasts
  `<Podcasts folder>/<Show>/` (names made safe for every OS; an existing author / show
  folder is reused whatever its case).
- **File names**: audiobooks `NN - <chapter title>.<ext>` (NN = position in the reviewed
  order, 2 digits or more); podcasts `<YYYY-MM-DD> - <episode title>.<ext>`.
- Only the audio files and the chosen cover (`cover.jpg`) go into the folder; the rest
  of the source (sub-folders, .nfo, other pictures) is left behind.
- The import mode applies: **copy** (the source is untouched) or **move** (the source
  folders are removed once empty of audio).
- **Tags written** into the imported files (mediafile): album = title / show, album
  artist and artist = author, composer = narrator, title = chapter / episode title,
  track = position / total, disc cleared, compilation cleared, year / date, genre,
  grouping = "Series, Book N" when a series is set, comments = description. The
  chapters inside a file (M4B) are kept.
- An **existing book** (its folder already holds audio files) is not mixed: the task goes
  back to the review with the error. An **existing show** gets the new episodes (an
  episode whose file name already exists is skipped and listed).
- Then a targeted scan, as for music: the book / show is on its page when the task shows
  "imported".

## 6. Out of scope

- Chapter names from Audible / Audnexus: they describe the edition's chapters, which do
  not map to the files (MusicBrainz track lists do, see §4); writing chapter lists into
  M4B files.
- Splitting one folder into several books.
- Showing the series / narrator on the book page (they are in the tags for later).
- Editing the metadata of books already in the library.
