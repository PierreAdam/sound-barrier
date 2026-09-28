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

// --- Manage Library ---------------------------------------------------------------

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
}

export interface BrowseResponse {
  root: string;
  path: string;
  parent: string | null; // null at the import root
  entries: FolderEntry[];
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
  result: { paths: string[]; converted?: number } | null;
  error: string | null;
  updatedAt: string;
}

export interface ImportJob {
  id: number;
  kind: "import" | "adopt"; // adopt: library albums added to beets
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
  player: { crossfade: boolean; crossfadeSeconds: number };
}

// --- web play queue ------------------------------------------------------------

/** The web UI's queue, kept on the server: one per user, shared by all browsers. */
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

// --- external services (artist information) --------------------------------------

export interface ExternalSettings {
  lastfmKeySet: boolean; // the keys themselves are never sent back
  fanartKeySet: boolean;
  pictureSource: string; // "none" or a provider id
  pictureSources: { id: string; label: string; needsKey: string | null }[];
}

/** A key: undefined keeps it, "" removes it, else the new key (checked by the server). */
export interface ExternalSettingsUpdate {
  lastfmKey?: string;
  fanartKey?: string;
  pictureSource?: string;
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

  getQueue: () => request<SavedQueue>("GET", "/queue"),
  getQueueRevision: () => request<{ revision: number }>("GET", "/queue/revision"),
  saveQueue: (queue: QueueToSave, keepalive = false) =>
    request<{ revision: number }>("PUT", "/queue", queue, { keepalive }),

  getExternalSettings: () => request<ExternalSettings>("GET", "/external/settings"),
  setExternalSettings: (settings: ExternalSettingsUpdate) =>
    request<ExternalSettings>("PUT", "/external/settings", settings),
  getArtistInfo: (artistId: string) => request<ArtistInfo>("GET", `/artists/${artistId}/info`),
  refreshArtistInfo: (artistId: string) => request<ArtistInfo>("POST", `/artists/${artistId}/info/refresh`),

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
  startImport: (paths: string[]) => request<ImportJob>("POST", "/manage/imports", { paths }),
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
  deleteMusic: (albumIds: string[], songIds: string[]) =>
    request<DeleteResult>("POST", "/manage/delete", { albumIds, songIds }),
};
