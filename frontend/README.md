# Sound-Barrier web UI

Single-page app (React + TypeScript + Vite) talking to the backend through the
Subsonic API (`/rest`). Features added later on our own endpoints will use `/api`,
through a separate client.

## Run

```bash
# backend first (from backend/): .venv/Scripts/sound-barrier serve
npm install
npm run dev        # http://localhost:5173, proxies /rest and /api to http://localhost:4040
```

Set `SOUND_BARRIER_BACKEND_URL` to proxy to another backend.

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Type-check and build to `dist/` |
| `npm run typecheck` | Type-check only |
| `npm test` | Unit tests (Vitest) |

## Structure

```
src/
├── api/          subsonic.ts (Subsonic client, token auth), types.ts, useSubsonic.ts (data hook),
│                 native.ts (our own /api: session cookie, library, scans, schedule)
├── auth/         AuthContext: login, session restore, logout
├── player/       engine.ts (queue, shuffle, repeat, crossfade on two <audio> decks),
│                 queue.ts (pure queue logic), PlayerContext (React + OS media keys)
├── components/   AppShell (layout), TopBar, SidePanel (pages + artist index),
│                 PlayerDock = PlayerBar + QueuePanel (opens on hover, drag-and-drop reorder),
│                 CoverArt, LoginPage, Icons
├── pages/        Home, Browse (index), Artist, Album, About,
│                 Account (everyone, from the username in the top bar): account/ (password, player),
│                 Settings (admins only): settings/ (library + scan progress, schedule, users),
│                 Manage Library (admins only): manage/ (import + browser, review, delete)
└── theme/        theme.less: every style, design tokens at the top
```

- **Styling:** all CSS lives in `src/theme/theme.less`. Components only use class names
  (BEM-style: `block__element--modifier`). Re-theme by editing the variables at the top.
- **Auth:** Subsonic token auth (`t = md5(password + salt)`). The password is never stored.
  The token is kept in `sessionStorage`, or in `localStorage` with "Remember me".
- **API calls** are form POSTs (OpenSubsonic `formPost`), so credentials stay out of URLs
  except where a URL is required (`stream`, `getCoverArt`).
