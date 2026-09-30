// Subsonic / OpenSubsonic response payloads used by the web UI (JSON format).

export interface ResponseEnvelope {
  status: "ok" | "failed";
  version: string;
  type?: string;
  serverVersion?: string;
  openSubsonic?: boolean;
  error?: { code: number; message: string };
}

export interface License {
  valid: boolean;
}

export interface OpenSubsonicExtension {
  name: string;
  versions: number[];
}

export interface MusicFolder {
  id: number;
  name?: string;
}

export interface User {
  username: string;
  email?: string;
  adminRole: boolean;
  streamRole: boolean;
  downloadRole: boolean;
  playlistRole: boolean;
  coverArtRole: boolean;
  scrobblingEnabled: boolean;
  folder?: number[];
}

export interface ScanStatus {
  scanning: boolean;
  count?: number;
  lastScan?: string;
}

export interface ArtistRef {
  id: string;
  name: string;
}

export interface ArtistID3 {
  id: string;
  name: string;
  coverArt?: string;
  albumCount: number;
  starred?: string;
  userRating?: number;
  musicBrainzId?: string;
  sortName?: string;
}

export interface ArtistIndex {
  name: string;
  artist: ArtistID3[];
}

export interface AlbumID3 {
  id: string;
  name: string;
  artist?: string;
  artistId?: string;
  coverArt?: string;
  songCount: number;
  duration: number;
  created: string;
  playCount?: number; // by the user
  played?: string; // last played by the user
  year?: number;
  genre?: string;
  genres?: { name: string }[];
  artists?: ArtistRef[];
  displayArtist?: string;
  releaseTypes?: string[];
  recordLabels?: { name: string }[];
  isCompilation?: boolean;
  discTitles?: { disc: number; title: string }[];
}

export interface Playlist {
  id: string;
  name: string;
  comment?: string;
  owner: string;
  public: boolean;
  songCount: number;
  duration: number;
  created: string;
  changed: string;
  coverArt?: string;
}

/** A song. */
export interface Child {
  id: string;
  parent?: string;
  isDir: boolean;
  title: string;
  album?: string;
  artist?: string;
  track?: number;
  year?: number;
  genre?: string;
  coverArt?: string;
  size?: number;
  contentType?: string;
  suffix?: string;
  duration?: number;
  bitRate?: number;
  path?: string;
  discNumber?: number;
  albumId?: string;
  artistId?: string;
  artists?: ArtistRef[];
  displayArtist?: string;
  displayAlbumArtist?: string;
  playCount?: number; // by the user
  mediaType?: "song" | "audiobook" | "podcast"; // OpenSubsonic
  bookmarkPosition?: number; // ms: where the user stopped (audiobooks, podcasts)
  chapters?: { startMs: number; title: string }[]; // inside the file (our /api only, audiobooks)
}

/** Payload of each method, keyed by method name. */
export interface SubsonicPayloads {
  ping: object;
  getLicense: { license: License };
  getOpenSubsonicExtensions: { openSubsonicExtensions: OpenSubsonicExtension[] };
  getMusicFolders: { musicFolders: { musicFolder?: MusicFolder[] } };
  getUser: { user: User };
  getUsers: { users: { user?: User[] } };
  createUser: object;
  updateUser: object;
  deleteUser: object;
  changePassword: object;
  getArtists: { artists: { ignoredArticles: string; index?: ArtistIndex[] } };
  getArtist: { artist: ArtistID3 & { album?: AlbumID3[] } };
  getAlbum: { album: AlbumID3 & { song?: Child[] } };
  getAlbumList2: { albumList2: { album?: AlbumID3[] } };
  scrobble: object;
  getPlaylists: { playlists: { playlist?: Playlist[] } };
  getPlaylist: { playlist: Playlist & { entry?: Child[] } };
  createPlaylist: { playlist: Playlist & { entry?: Child[] } };
  updatePlaylist: object;
  deletePlaylist: object;
  search3: { searchResult3: { artist?: ArtistID3[]; album?: AlbumID3[]; song?: Child[] } };
  getSong: { song: Child };
  createBookmark: object;
  deleteBookmark: object;
  getScanStatus: { scanStatus: ScanStatus };
  startScan: { scanStatus: ScanStatus };
  // OpenSubsonic "songLyrics": `start` in ms on synced lines.
  getLyricsBySongId: {
    lyricsList: { structuredLyrics?: { synced: boolean; line?: { start?: number; value: string }[] }[] };
  };
}

export type SubsonicMethod = keyof SubsonicPayloads;
export type SubsonicResponse<M extends SubsonicMethod> = ResponseEnvelope & SubsonicPayloads[M];
