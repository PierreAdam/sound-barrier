import { readFileSync } from "node:fs";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/** The packages that ship in the web UI (the lock file's non-dev ones), for the About page. */
function webLibraries() {
  const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as {
    dependencies?: Record<string, string>;
  };
  const lock = JSON.parse(readFileSync(new URL("./package-lock.json", import.meta.url), "utf8")) as {
    packages: Record<string, { version?: string; license?: string; dev?: boolean }>;
  };
  const direct = new Set(Object.keys(pkg.dependencies ?? {}));
  return Object.entries(lock.packages)
    .filter(([path, entry]) => path.startsWith("node_modules/") && !entry.dev)
    .map(([path, entry]) => {
      const name = path.slice(path.lastIndexOf("node_modules/") + "node_modules/".length);
      return { name, version: entry.version ?? "?", license: entry.license ?? null, direct: direct.has(name) };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

// The backend (sound-barrier serve) listens on 4040 by default. 127.0.0.1 rather than
// "localhost": on Windows, localhost tries IPv6 first and each request pays ~200 ms
// before falling back to the IPv4 socket uvicorn listens on.
const backend = process.env.SOUND_BARRIER_BACKEND_URL ?? "http://127.0.0.1:4040";

export default defineConfig({
  plugins: [react()],
  define: {
    // Set by npm when running `npm run dev` / `npm run build`.
    __APP_VERSION__: JSON.stringify(process.env.npm_package_version ?? "dev"),
    // When the web UI was built (in development: when the dev server started).
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
    // The web UI's libraries (About page).
    __WEB_LIBRARIES__: JSON.stringify(webLibraries()),
  },
  server: {
    port: 5173,
    // Same-origin requests in development: no CORS needed.
    proxy: {
      "/rest": backend,
      // Remote control's WebSocket (before "/api": the first match wins).
      "/api/remote/ws": { target: backend, ws: true },
      "/api": backend,
    },
  },
  test: {
    environment: "jsdom",
  },
});
