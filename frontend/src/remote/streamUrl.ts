/**
 * The server player's stream URL and its options, as the backend reads them
 * (api/server_player.py `stream`): only those changed from the defaults are written.
 */

/** The bit rates the stream offers, in kbps (services/server_player.py `BIT_RATES`). */
export const BIT_RATES = [64, 96, 128, 160, 192, 256, 320] as const;
export const DEFAULT_BIT_RATE = 192;
/** Seconds of sound a device gets at once when it connects (`BURST_SECONDS`), at most. */
export const DEFAULT_BURST = 2;
export const MAX_BURST = 10;

export interface StreamOptions {
  bitRate: number; // kbps
  burst: number; // seconds
  titles: boolean; // the title playing, to the internet radio apps asking for it
}

export const DEFAULT_STREAM_OPTIONS: StreamOptions = { bitRate: DEFAULT_BIT_RATE, burst: DEFAULT_BURST, titles: true };

export function streamUrlWith(streamUrl: string, options: StreamOptions): string {
  const url = new URL(streamUrl);
  if (options.bitRate !== DEFAULT_BIT_RATE) url.searchParams.set("bitrate", String(options.bitRate));
  if (options.burst !== DEFAULT_BURST) url.searchParams.set("burst", String(options.burst));
  if (!options.titles) url.searchParams.set("titles", "0");
  return url.toString();
}
