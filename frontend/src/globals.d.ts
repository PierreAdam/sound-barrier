/** Web UI version, injected by Vite (see vite.config.ts). */
declare const __APP_VERSION__: string;
/** Build date and time (ISO 8601, UTC), injected by Vite. */
declare const __BUILD_TIME__: string;
/** The packages that ship in the web UI, injected by Vite (About page). */
declare const __WEB_LIBRARIES__: { name: string; version: string; license: string | null; direct: boolean }[];
