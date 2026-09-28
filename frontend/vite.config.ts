import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

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
  },
  server: {
    port: 5173,
    // Same-origin requests in development: no CORS needed.
    proxy: {
      "/rest": backend,
      "/api": backend,
    },
  },
  test: {
    environment: "jsdom",
  },
});
