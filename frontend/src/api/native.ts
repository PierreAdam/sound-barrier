// Client for our own API (`/api`): features the Subsonic API does not cover.
// Authentication is an HttpOnly session cookie set by POST /api/auth/login.

import type { Appearance } from "../theme/appearance";
import type { Child } from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: { keepalive?: boolean } = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      // Lets a request finish after the page is closed (browsers cap the body at 64 KB).
      keepalive: options.keepalive,
    });
  } catch (cause) {
    console.error(`API ${method} ${path} failed`, cause);
    throw new ApiError(0, "Cannot reach the server");
  }
  if (response.status === 204) return undefined as T;
  const data = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : `Server error (HTTP ${response.status})`;
    throw new ApiError(response.status, detail);
  }
  return data as T;
}

// --- types (JSON is camelCase) -------------------------------------------------

export interface Me {
  username: string;
  admin: boolean;
}

export interface LibraryFolder {
  id: number;
  name: string;
  path: string;
  reachable: boolean;
}

export interface ScanInfo {
  id: number;
  kind: "quick" | "full" | "targeted";
  status: "running" | "done" | "failed";
  phase: "starting" | "walking" | "reading" | "finishing" | "done" | "failed";
  startedAt: string;
  finishedAt: string | null;
  filesSeen: number;
  filesToRead: number;
  filesRead: number;
  added: number;
  updated: number;
  removed: number;
  error: string | null;
}

export interface ScanStatus {
  running: boolean;
  songCount: number;
  latest: ScanInfo | null;
  nextRunAt: string | null;
}

export interface ScanSchedule {
  enabled: boolean;
  time: string; // HH:MM, server local time
  scanOnStartup: boolean;
}

export interface ScheduleResponse extends ScanSchedule {
  nextRunAt: string | null;
  timeZone: string;
}

// --- Library Management ---------------------------------------------------------------

export interface ManageSettings {
  root: string | null; // import root folder
  rootReachable: boolean;
  mode: "copy" | "move";
  autoApplyStrong: boolean;
  transcodeLossless: boolean; // FLAC, WAV... converted to MP3 320 kbps while importing
  ffmpegAvailable: boolean;
  tagger: string;
  matching: boolean; // false: albums can only be imported with their current tags
}

export interface ManageSettingsUpdate {
  root: string | null;
  autoApplyStrong: boolean;
  transcodeLossless: boolean;
}

export interface FolderEntry {
  name: string;
  path: string;
  isDir: boolean;
  audioFiles: number;
  size: number;
  created: string; // ISO; the last modification where the server's OS keeps no creation time
}

export interface BrowseResponse {
  root: string;
  path: string;
  parent: string | null; // null at the import root
  entries: FolderEntry[];
}

/** An album folder of the import browser that is already in the library. */
export interface InLibraryFolder {
  path: string;
  albumId: string;
  album: string;
  artist: string;
  tracks: number; // audio files in the folder
  libraryTracks: number | null; // of them in the library; null: unknown (no title tags)
  reason: "tags" | "name" | "imported";
}

export interface ImportItem {
  path: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  album_artist: string | null;
  track: number | null;
  disc: number | null;
  year: number | null;
  duration_ms: number | null;
}

export interface CandidateTrack {
  title: string;
  artist: string | null;
  track: number | null;
  disc: number | null;
  duration_ms: number | null;
  item_index: number | null;
  issues?: string[]; // what differs from the file: "duration", "title", "track number"...
}

/** One reason why a candidate is not a 100 % match (beets' distance penalties). */
export interface Penalty {
  key: string;
  label: string;
  share: number; // of the match lost: 0.05 = 5 points
  current: string | null; // the files' value
  proposed: string | null; // the candidate's value
  detail: string | null;
}

export interface Candidate {
  id: string;
  source: string;
  artist: string;
  album: string;
  distance: number; // 0 = perfect
  year: number | null;
  label: string | null;
  country: string | null;
  media: string | null;
  catalog_number: string | null;
  url: string | null;
  tracks: CandidateTrack[];
  extra_items: number[];
  penalties?: Penalty[]; // biggest first; absent for albums identified before this existed
}

export type TaskStatus =
  | "queued"
  | "analyzing"
  | "pending"
  | "converting"
  | "applying"
  | "imported"
  | "skipped"
  | "failed";

export interface ImportTask {
  id: number;
  jobId: number;
  sourceDir: string;
  status: TaskStatus;
  items: ImportItem[];
  candidates: Candidate[];
  recommendation: "strong" | "medium" | "low" | "none" | null;
  decision: { action: string; candidateId?: string; auto?: boolean } | null;
  result: { paths: string[]; converted?: number; folder?: string; skipped?: string[] } | null;
  error: string | null;
  updatedAt: string;
  /** Audiobooks / podcasts: what the review starts from (snake_case, like items). */
  spoken?: SpokenReview | null;
}

/** An audio file of a book / show being imported (its tags). */
export interface SpokenFile {
  path: string;
  title: string | null;
  artist: string | null;
  album: string | null;
  album_artist: string | null;
  composer: string | null;
  track: number | null;
  disc: number | null;
  year: number | null;
  date: string | null;
  genre: string | null;
  duration_ms: number;
  has_picture: boolean;
  chapters: number; // inside the file
}

export interface SpokenEntry {
  path: string;
  title: string;
  date: string | null; // podcasts: YYYY-MM-DD
}

export interface SpokenProposal {
  title: string;
  author: string;
  narrator: string | null;
  series: string | null;
  series_number: string | null;
  year: number | null;
  genre: string | null;
  description: string | null;
  cover: string | null; // "folder:<path>", "embedded:<path>", "url:<url>"
  entries: SpokenEntry[];
}

export interface SpokenReview {
  kind: "audiobook" | "podcast";
  folders: string[];
  images: string[]; // pictures in the folders
  proposal: SpokenProposal;
  lookup: { query: { title: string; author: string | null }; errors: string[] };
}

/** A folder of the import browser that looks like audiobooks / podcasts. */
export interface KindHint {
  path: string;
  kind: "audiobook" | "podcast";
  reason: string; // e.g. 'genre "Audiobook"'
}

/** A book / show found online (Audible, Open Library, iTunes). */
export interface BookCandidate {
  id: string;
  source: string;
  title: string;
  authors: string[];
  narrators: string[];
  series: string | null;
  series_number: string | null;
  year: number | null;
  duration_ms: number | null;
  description: string | null;
  genre: string | null;
  cover_url: string | null;
  url: string | null;
  // MusicBrainz: the edition's track count, and its tracks when it matches the files.
  track_count: number | null;
  tracks: { title: string; duration_ms: number | null }[];
  release_group_id: string | null;
}

/** The reviewed metadata sent back (camelCase). */
export interface SpokenImport {
  title: string;
  author: string;
  narrator: string | null;
  series: string | null;
  seriesNumber: string | null;
  year: number | null;
  genre: string | null;
  description: string | null;
  cover: string | null;
  entries: SpokenEntry[];
  // The MusicBrainz edition used (written to the tags).
  musicbrainzReleaseId?: string | null;
  musicbrainzReleaseGroupId?: string | null;
}

export interface ImportJob {
  id: number;
  // adopt: library albums added to beets; podcast / audiobook: reviewed, then placed in that folder
  kind: "import" | "adopt" | "podcast" | "audiobook";
  sources: string[];
  status: "queued" | "running" | "done" | "failed";
  error: string | null;
  createdAt: string;
  finishedAt: string | null;
  tasks: ImportTask[];
}

export interface UnknownFolder {
  path: string; // relative to the library folder
  artist: string;
  album: string;
  songs: number;
  unknownSongs: number;
}

/** The library against the tagger's database (beets). */
export interface LibraryStatus {
  libraryPath: string;
  albums: number;
  songs: number;
  sizeBytes: number; // the songs' files on the disk
  tagger: string;
  hasTaggerDatabase: boolean;
  taggerAlbums: number;
  taggerSongs: number;
  taggerMissing: number;
  unknownFolderCount: number;
  unknownFolders: UnknownFolder[];
}

export interface DeleteResult {
  songs: number;
  filesDeleted: number;
  filesAlreadyGone: number;
  foldersRemoved: string[];
}

// --- preferences ---------------------------------------------------------------

/** Saved on the server: they follow the user from one device to another. */
export interface UserPreferences {
  theme: Appearance;
  player: { crossfade: boolean; crossfadeSeconds: number; spokenSpeed: number }; // spokenSpeed: 1 to 2
  /** Release group categories shown in "Missing albums" (e.g. "album", "album+live"). */
  discography: { categories: string[]; recentMonths: number }; // recentMonths: New releases, 1 to 12
  lyrics: { karaoke: boolean }; // "Now playing": the current line fills word by word
}

// --- web play queue ------------------------------------------------------------

/**
 * A player's queue, kept on the server: the Shared one (every browser not assigned to a
 * player), or that of a player the user created (`playerId`).
 */
export interface SavedQueue {
  revision: number; // 0: never saved
  songs: Child[]; // play order
  originalOrder: number[] | null; // shuffled: play positions in the original order
  currentIndex: number;
  positionMs: number;
  updatedAt: string | null;
}

export interface QueueToSave {
  songIds: string[];
  originalOrder: number[] | null;
  currentIndex: number;
  positionMs: number;
}

/** A player the user created (e.g. "Phone"): browsers assigned to it play its own queue. */
export interface WebPlayer {
  id: string;
  name: string;
  songCount: number; // in its queue
  createdAt: string;
  updatedAt: string; // its queue's last save
}

export interface WebPlayers {
  shared: { songCount: number; updatedAt: string | null }; // updatedAt null: never saved
  players: WebPlayer[]; // by name
  maxPlayers: number;
}

/** `?player=` for a player's queue, nothing for the Shared one. */
const playerQuery = (playerId: string | null) => (playerId ? `?player=${encodeURIComponent(playerId)}` : "");

// --- external services (artist information) --------------------------------------

export interface ExternalSettings {
  lastfmKeySet: boolean; // the keys themselves are never sent back
  fanartKeySet: boolean;
  pictureSource: string; // "none" or a provider id
  pictureSources: { id: string; label: string; needsKey: string | null }[];
  musicbrainz: boolean; // discographies ("Missing albums" on artist pages)
  lrclib: boolean; // song lyrics from lrclib.net
  // Audiobook / podcast import review lookups.
  audible: boolean;
  audibleRegion: string;
  audibleRegions: string[];
  openLibrary: boolean;
  itunes: boolean;
}

/** A key: undefined keeps it, "" removes it, else the new key (checked by the server). */
export interface ExternalSettingsUpdate {
  lastfmKey?: string;
  fanartKey?: string;
  pictureSource?: string;
  musicbrainz?: boolean;
  lrclib?: boolean;
  audible?: boolean;
  audibleRegion?: string;
  openLibrary?: boolean;
  itunes?: boolean;
}

export interface ArtistInfo {
  lastfmConfigured: boolean;
  lastfmUrl: string | null;
  summary: string | null;
  biography: string | null;
  similar: { name: string; id: string | null }[]; // id: in the library
  topSongs: Child[]; // songs of the library, most popular first
  picture: { source: string; pageUrl: string | null; coverArt: string } | null;
  error: string | null; // admins only
}

// --- discography (MusicBrainz) ------------------------------------------------

export interface ReleaseGroup {
  mbid: string;
  title: string;
  category: string; // "album", "album+live", "ep+demo"...
  primaryType: string | null;
  secondaryTypes: string[];
  firstReleaseDate: string | null; // partial ISO date
  upcoming: boolean;
  owned: { albumId: string; name: string; coverArt: string | null } | null; // in the library
}

export interface Discography {
  enabled: boolean; // MusicBrainz lookups allowed in Settings
  artistMbid: string | null;
  mbidSource: "manual" | "tags" | "search" | null; // null: not linked to MusicBrainz
  fetchedAt: string | null;
  error: string | null; // admins only
  categories: { key: string; label: string; total: number; missing: number }[]; // display order
  releaseGroups: ReleaseGroup[]; // by category, then date
}

/** A release of an artist of the library that the library does not have (New releases). */
export interface NewRelease extends ReleaseGroup {
  artistId: string;
  artistName: string;
  monthUnknown: boolean; // only the year is known
}

/** The background refresh of the discographies (server side: it goes on without the page). */
export interface DiscographySync {
  running: boolean;
  total: number; // artists to fetch in this run
  done: number;
  current: string | null;
  errors: number;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface NewReleases {
  enabled: boolean; // MusicBrainz lookups allowed in Settings
  sync: DiscographySync;
  artists: number;
  stale: number; // artists whose discography must be fetched (again)
  upcoming: NewRelease[]; // soonest first
  recent: NewRelease[]; // newest first
  categories: { key: string; label: string; count: number }[];
  unlinked: { id: string; name: string }[]; // not linked to MusicBrainz
}

export interface MusicBrainzArtist {
  mbid: string;
  name: string;
  disambiguation: string | null;
  country: string | null;
  type: string | null;
  begin: string | null;
  end: string | null;
  score: number;
}

// --- plugins (admins) -----------------------------------------------------------

/** A settings field, described by the plugin (the form is built from these). */
export interface PluginField {
  key: string;
  label: string;
  type: "text" | "textarea" | "boolean" | "select" | "list";
  help: string | null;
  placeholder: string | null;
  options: string[]; // select
  visibleWhen: [string, string] | null; // shown when that sibling field has that value
  // list
  fields: PluginField[];
  itemLabel: string | null; // sub-field naming a row
  idKey: string | null; // sub-field identifying a row (given by the plugin)
  iconAsset: string | null; // a row's icon ("{id}" replaced)
  canTry: boolean;
}

export type PluginSettings = Record<string, unknown>;

export interface PluginInfo {
  id: string;
  name: string;
  description: string;
  capabilities: string[]; // "links"
  fields: PluginField[];
  enabled: boolean;
  settings: PluginSettings;
}

/** A way to find an album: a page to open, or a form the browser submits (POST). */
export interface AlbumLink {
  label: string;
  url: string;
  method: "GET" | "POST";
  form: [string, string][];
  iconUrl: string | null;
}

export interface PluginLinks {
  plugin: string;
  name: string;
  links: AlbumLink[];
}

// --- lyrics -------------------------------------------------------------------

/** A library the server runs on (About page). */
export interface ServerLibrary {
  name: string;
  version: string;
  license: string | null;
  summary: string | null;
  url: string | null;
  direct: boolean; // declared by Sound-Barrier (else needed by another library)
}

/** What the server runs on (admins only). */
export interface ServerRuntime {
  version: string;
  python: string;
  os: string;
  kernel: string;
  architecture: string;
  container: boolean;
  cpus: number | null;
  postgres: string | null;
  ffmpeg: string | null;
  timeZone: string;
  startedAt: string;
  uptimeS: number;
}

export interface SongLyrics {
  found: boolean;
  unavailable: boolean; // LRCLIB could not be asked: try again later
  source: "lrc" | "embedded" | "transcript" | "lrclib" | null; // transcript: speech to text
  synced: boolean; // lines have a start time
  instrumental: boolean;
  // words: word by word timing ("enhanced LRC"), when the lyrics have it
  lines: { startMs: number | null; text: string; words: { startMs: number; text: string }[] | null }[];
}

// --- transcripts (speech to text, by the companion app `transcriber/`) ----------

export interface WorkerToken {
  id: string;
  name: string;
  createdAt: string;
  lastUsedAt: string | null;
}

export interface TranscriptBook {
  id: string;
  kind: SpokenKind;
  title: string;
  author: string;
  coverArt: string | null;
  files: number;
  durationMs: number;
  done: number;
  working: number;
  failed: number;
  pending: number;
}

export interface TranscriptWork {
  songId: string;
  albumId: string;
  book: string;
  title: string;
  worker: string | null;
  progress: number; // 0..1
  startedAt: string;
  updatedAt: string;
}

export interface TranscriptFile {
  id: string;
  title: string;
  fileName: string;
  durationMs: number;
  size: number;
  status: "pending" | "working" | "done" | "failed";
  progress: number;
  worker: string | null;
  error: string | null;
  updatedAt: string | null;
}

// --- podcasts and audiobooks ----------------------------------------------------

export type SpokenKind = "podcasts" | "audiobooks";

/** A library section (podcasts / audiobooks): its folder and its admin switch. */
export interface SpokenFolder {
  enabled: boolean;
  folder: LibraryFolder | null;
}

export interface SpokenShow {
  id: string;
  kind: SpokenKind;
  title: string;
  author: string;
  coverArt: string | null;
  episodes: number;
  durationMs: number;
  latest: string | null;
  started: number; // episodes / chapters with a bookmark
  played: number;
  year: number | null;
  narrator: string | null; // audiobooks
  series: string | null; // audiobooks: the series, and the book's number in it
  seriesNumber: string | null;
}

/** A show's / book's page: its episodes / chapters and the details of its tags. */
export interface SpokenShowData {
  show: SpokenShow;
  episodes: Child[];
  description: string | null;
  genre: string | null;
}

/** A file of a book / show in "Edit details": its title and the chapters inside it. */
export interface SpokenFileDetails {
  id: string;
  title: string;
  chapters: { startMs: number; title: string }[] | null;
  fileName: string; // read only
  durationMs: number;
  canWriteChapters: boolean; // MP3, M4A / M4B
}

export interface AudibleBook {
  asin: string;
  title: string;
  authors: string[];
  narrators: string[];
  series: string | null;
  seriesNumber: string | null;
  durationMs: number | null;
  coverUrl: string | null;
  url: string | null;
}

/** A book's chapters on Audible, timed in Audible's file (it starts with a jingle, introMs). */
export interface AudibleChapters {
  asin: string;
  runtimeMs: number;
  introMs: number;
  outroMs: number;
  accurate: boolean;
  chapters: { startMs: number; lengthMs: number; title: string }[];
}

/** What admins can change after the import (written into the files' tags). */
export interface SpokenDetails {
  title: string;
  author: string;
  narrator: string | null;
  series: string | null;
  seriesNumber: string | null;
  year: number | null;
  genre: string | null;
  description: string | null;
  files?: SpokenFileDetails[]; // in listening order
}

export interface SpokenPage {
  continueListening: { show: SpokenShow; episode: Child; changedAt: string }[];
  shows: SpokenShow[];
}

// --- tag editor (admins) -----------------------------------------------------

export interface AlbumTags {
  album: string;
  albumArtist: string | null;
  year: number | null;
  genre: string | null;
  compilation: boolean;
  tracks: { id: string; path: string; disc: number | null; track: number | null; title: string; artist: string | null }[];
}

// --- album covers (admins) ---------------------------------------------------

export interface CoverResult {
  source: string;
  sourceLabel: string;
  title: string;
  artist: string;
  imageUrl: string;
  thumbnailUrl: string; // through our server
  width: number | null;
  height: number | null;
  pageUrl: string | null;
}

// --- endpoints -----------------------------------------------------------------

export const api = {
  login: (username: string, password: string, remember: boolean) =>
    request<Me>("POST", "/auth/login", { username, password, remember }),
  logout: () => request<void>("POST", "/auth/logout"),
  me: () => request<Me>("GET", "/auth/me"),
  changeOwnPassword: (password: string) => request<void>("PUT", "/auth/password", { password }),

  /** Changes whenever the library may have changed (after every scan, import, deletion). */
  getPreferences: () => request<UserPreferences>("GET", "/preferences"),
  setPreferences: (preferences: UserPreferences) => request<UserPreferences>("PUT", "/preferences", preferences),

  getQueue: (playerId: string | null) => request<SavedQueue>("GET", `/queue${playerQuery(playerId)}`),
  getQueueRevision: (playerId: string | null) =>
    request<{ revision: number }>("GET", `/queue/revision${playerQuery(playerId)}`),
  saveQueue: (playerId: string | null, queue: QueueToSave, keepalive = false) =>
    request<{ revision: number }>("PUT", `/queue${playerQuery(playerId)}`, queue, { keepalive }),
  getPlayers: () => request<WebPlayers>("GET", "/players"),
  createPlayer: (name: string) => request<WebPlayer>("POST", "/players", { name }),
  renamePlayer: (id: string, name: string) =>
    request<WebPlayer>("PUT", `/players/${encodeURIComponent(id)}`, { name }),
  deletePlayer: (id: string) => request<void>("DELETE", `/players/${encodeURIComponent(id)}`),

  getExternalSettings: () => request<ExternalSettings>("GET", "/external/settings"),
  setExternalSettings: (settings: ExternalSettingsUpdate) =>
    request<ExternalSettings>("PUT", "/external/settings", settings),
  getArtistInfo: (artistId: string) => request<ArtistInfo>("GET", `/artists/${artistId}/info`),
  refreshArtistInfo: (artistId: string) => request<ArtistInfo>("POST", `/artists/${artistId}/info/refresh`),
  getDiscography: (artistId: string) => request<Discography>("GET", `/artists/${artistId}/discography`),
  refreshDiscography: (artistId: string) =>
    request<Discography>("POST", `/artists/${artistId}/discography/refresh`),
  /** A release group's cover (an <img> source; 404 when there is none). */
  discographyCoverUrl: (artistId: string, mbid: string) => `/api/artists/${artistId}/discography/covers/${mbid}`,
  searchMusicBrainzArtists: (artistId: string, query?: string) =>
    request<MusicBrainzArtist[]>(
      "GET",
      `/artists/${artistId}/musicbrainz/candidates${query ? `?q=${encodeURIComponent(query)}` : ""}`,
    ),
  /** An id or a musicbrainz.org URL; null goes back to the tags / the search. */
  linkMusicBrainz: (artistId: string, mbid: string | null) =>
    request<Discography>("PUT", `/artists/${artistId}/musicbrainz`, { mbid }),

  getPlugins: () => request<PluginInfo[]>("GET", "/plugins"),
  savePlugin: (pluginId: string, enabled: boolean, settings: PluginSettings, refresh = false) =>
    request<{ plugin: PluginInfo; warnings: string[] }>("PUT", `/plugins/${pluginId}`, { enabled, settings, refresh }),
  /** The links of one row of a list field (saved or not), for a sample album. */
  tryPlugin: (pluginId: string, settings: PluginSettings, field: string, item: number) =>
    request<AlbumLink[]>("POST", `/plugins/${pluginId}/try`, { settings, field, item }),
  pluginAssetUrl: (pluginId: string, name: string) => `/api/plugins/${pluginId}/assets/${name}`,
  getNewReleases: (months: number) => request<NewReleases>("GET", `/manage/new-releases?months=${months}`),
  /** Starts refreshing the old discographies (nothing if a refresh is running). */
  syncNewReleases: () => request<DiscographySync>("POST", "/manage/new-releases/sync"),
  getReleaseGroupLinks: (artistId: string, mbid: string) =>
    request<PluginLinks[]>("GET", `/artists/${artistId}/discography/${mbid}/links`),

  getSongLyrics: (songId: string) => request<SongLyrics>("GET", `/songs/${songId}/lyrics`),
  /** The server's libraries; its runtime for admins (else null). */
  getAbout: () => request<{ libraries: ServerLibrary[]; runtime: ServerRuntime | null }>("GET", "/about"),

  getAlbumTags: (albumId: string) => request<AlbumTags>("GET", `/albums/${albumId}/tags`),
  setAlbumTags: (albumId: string, tags: AlbumTags) =>
    request<{ albumId: string | null; files: number }>("PUT", `/albums/${albumId}/tags`, tags),
  searchCovers: (albumId: string, query?: string) =>
    request<{ query: string; results: CoverResult[]; errors: string[] }>(
      "GET",
      `/albums/${albumId}/cover-search${query ? `?q=${encodeURIComponent(query)}` : ""}`,
    ),
  setAlbumCover: (albumId: string, imageUrl: string, embed: boolean) =>
    request<{ coverArt: string | null; folders: string[]; embedded: number }>("POST", `/albums/${albumId}/cover`, {
      imageUrl,
      embed,
    }),

  getLibraryRevision: () => request<{ revision: number }>("GET", "/library/revision"),
  getSpokenFolders: () => request<Record<SpokenKind, SpokenFolder>>("GET", "/library/spoken"),
  /** path: undefined keeps the folder, "" removes it. */
  setSpokenFolder: (kind: SpokenKind, enabled: boolean, path?: string) =>
    request<Record<SpokenKind, SpokenFolder>>("PUT", `/library/spoken/${kind}`, { enabled, path }),
  /** The sections this user has (on, with a folder). */
  getSections: () => request<Record<SpokenKind, boolean>>("GET", "/library/sections"),
  getSpokenPage: (kind: SpokenKind) => request<SpokenPage>("GET", `/spoken/${kind}`),
  getSpokenShow: (id: string) => request<SpokenShowData>("GET", `/spoken/shows/${id}`),
  getSpokenDetails: (id: string) => request<SpokenDetails>("GET", `/spoken/shows/${id}/details`),
  /** Returns the show's / book's id afterwards (it changes with its title). */
  setSpokenDetails: (id: string, details: SpokenDetails) =>
    request<{ id: string }>("PUT", `/spoken/shows/${id}/details`, details),
  searchAudible: (title: string, author?: string) =>
    request<AudibleBook[]>(
      "GET",
      `/spoken/audible/search?${new URLSearchParams({ title, ...(author ? { author } : {}) }).toString()}`,
    ),
  getAudibleChapters: (asin: string) => request<AudibleChapters>("GET", `/spoken/audible/${asin}/chapters`),
  /** Removes the user's bookmarks of a show / book (out of "Continue listening", or started over). */
  forgetSpokenShow: (id: string) => request<void>("DELETE", `/spoken/shows/${id}/bookmarks`),
  getLibrary: () => request<{ folder: LibraryFolder | null }>("GET", "/library"),
  setLibrary: (path: string, name: string) =>
    request<{ folder: LibraryFolder }>("PUT", "/library", { path, name }),

  getScan: () => request<ScanStatus>("GET", "/scan"),
  startScan: (full: boolean) => request<ScanStatus>("POST", "/scan", { full }),
  getSchedule: () => request<ScheduleResponse>("GET", "/scan/schedule"),
  setSchedule: (schedule: ScanSchedule) => request<ScheduleResponse>("PUT", "/scan/schedule", schedule),

  getManageSettings: () => request<ManageSettings>("GET", "/manage/settings"),
  setManageSettings: (settings: ManageSettingsUpdate) => request<ManageSettings>("PUT", "/manage/settings", settings),
  browse: (path?: string) =>
    request<BrowseResponse>("GET", `/manage/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  /** The album folders of a listed folder already in the library (tags are read: slower). */
  browseInLibrary: (path?: string) =>
    request<InLibraryFolder[]>("GET", `/manage/browse/in-library${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  /** kind: music (beets matching), or podcast / audiobook (copied as is into that folder). */
  startImport: (paths: string[], kind: "music" | "podcast" | "audiobook" = "music") =>
    request<ImportJob>("POST", "/manage/imports", { paths, kind }),
  listImports: () => request<ImportJob[]>("GET", "/manage/imports"),
  getLibraryStatus: () => request<LibraryStatus>("GET", "/manage/library-status"),
  adopt: (paths: string[]) => request<ImportJob>("POST", "/manage/adopt", { paths }),
  forgetMissing: () => request<{ removed: number }>("POST", "/manage/forget-missing"),
  cleanup: () =>
    request<{ beetsBackups: number; beetsMissing: number; stagingFolders: number; cachedCovers: number; artistPictures: number }>(
      "POST",
      "/manage/cleanup",
    ),
  getReviewCounts: () => request<{ pending: number; failed: number }>("GET", "/manage/tasks/counts"),
  decideAll: (action: "skip" | "retry", status: "pending" | "failed") =>
    request<{ changed: number }>("POST", "/manage/tasks/bulk", { action, status }),
  decide: (taskId: number, action: "apply" | "as_is" | "skip" | "retry", candidateId?: string) =>
    request<ImportTask>("POST", `/manage/tasks/${taskId}/decision`, { action, candidateId }),
  search: (taskId: number, query: { artist?: string; album?: string; releaseId?: string }) =>
    request<ImportTask>("POST", `/manage/tasks/${taskId}/search`, query),
  importSpoken: (taskId: number, metadata: SpokenImport) =>
    request<ImportTask>("POST", `/manage/tasks/${taskId}/spoken/import`, metadata),
  /** Appends a waiting book to another one; returns that one. */
  mergeSpoken: (taskId: number, into: number) =>
    request<ImportTask>("POST", `/manage/tasks/${taskId}/spoken/merge`, { into }),
  lookupSpoken: (taskId: number, title: string, author: string | null) =>
    request<ImportTask>("POST", `/manage/tasks/${taskId}/spoken/lookup`, { title, author }),
  /** Preview of a "folder:" / "embedded:" cover of a waiting import. */
  spokenCoverUrl: (taskId: number, cover: string) =>
    `/api/manage/tasks/${taskId}/spoken/cover?cover=${encodeURIComponent(cover)}`,
  /** Folders of a listed folder that look like audiobooks / podcasts (a hint). */
  browseKinds: (path?: string) =>
    request<KindHint[]>("GET", `/manage/browse/kinds${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  deleteMusic: (albumIds: string[], songIds: string[]) =>
    request<DeleteResult>("POST", "/manage/delete", { albumIds, songIds }),

  // Transcripts (admins)
  getWorkerTokens: () => request<WorkerToken[]>("GET", "/transcripts/tokens"),
  /** The secret is only in this answer. */
  createWorkerToken: (name: string) =>
    request<{ token: WorkerToken; secret: string }>("POST", "/transcripts/tokens", { name }),
  revokeWorkerToken: (id: string) => request<void>("DELETE", `/transcripts/tokens/${id}`),
  getTranscripts: () => request<{ books: TranscriptBook[]; working: TranscriptWork[] }>("GET", "/transcripts"),
  getTranscriptBook: (albumId: string) =>
    request<{ book: TranscriptBook; files: TranscriptFile[] }>("GET", `/transcripts/books/${albumId}`),
  removeTranscripts: (albumId: string) => request<{ count: number }>("DELETE", `/transcripts/books/${albumId}`),
  retryTranscripts: (albumId: string) => request<{ count: number }>("POST", `/transcripts/books/${albumId}/retry`),
};
