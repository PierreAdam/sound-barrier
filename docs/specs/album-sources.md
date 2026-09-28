# Spec: plugins and album search links

Status: implemented (2026-09-28). Roadmap entry: [ROADMAP.md](../../ROADMAP.md) §5.
Builds on [missing-albums.md](missing-albums.md).

In "Missing albums", an admin clicking an album the library does not have gets a popup of
ways to find it: search links to sites chosen by the admin (Fnac, Amazon.fr, a store where
they buy music...). The links come from **plugins**, so other ways (e.g. downloading from
a digital store where the user buys music) can be added later.

## 1. Plugins

- Embedded in the backend: `backend/app/plugins/`, one sub-package per plugin, listed in
  the registry (`app/plugins/__init__.py`). No third-party plugins for now (the contract
  allows Python entry points later).
- A plugin declares an id, a name, a description, its **settings fields** and its
  **capabilities**. Only one capability exists for now:
  - `links`: links for an album (`WantedAlbum`: artist, title, year, MusicBrainz ids;
    nothing about the user) → a list of `AlbumLink` (label, URL, method GET / POST, form
    fields for POST, icon).
  - Later: e.g. `download` (search / fetch files from a store, then the import pipeline).
- Hooks: `validate(settings)` (refuses bad values, fills defaults), `saved(old, new)`
  (e.g. fetch icons), `asset(name)` (files the plugin serves, e.g. icons). A plugin gets a
  folder of its own in the data folder: `<data>/plugins/<plugin id>/`.
- Stored in `server_setting` under `plugin:<id>`: `{ enabled, settings }`. Default
  settings come from the plugin.

### Settings fields

The plugin describes its form; Settings renders it (no plugin-specific frontend code):

| Type | Notes |
|---|---|
| `text`, `textarea` | placeholder, help |
| `boolean` | |
| `select` | options |
| `list` | rows of sub-fields; drag and drop to reorder, add / remove rows; optional per-row icon (a plugin asset) and "Try" button (plugins with `links`) |

A field can be shown only when another one has a given value (`visible_when`, e.g. the
POST body only for POST).

## 2. The "Search links" plugin

- An **ordered list of sites** (the popup follows this order). Per site:
  - name, on/off;
  - method: `GET` or `POST`;
  - URL (GET: the search URL with placeholders);
  - POST body: as shown by the browser's dev tools (`application/x-www-form-urlencoded`,
    e.g. `SearchForm%5Bn%5D={query}&go-search=Search`), placeholders in the values;
  - icon URL (optional; else found automatically).
- **Placeholders**: `{query}` (artist and album), `{artist}`, `{album}`, `{year}`,
  `{mbid}` (release group). URL-encoded, spaces as `+`. The URL must be `http(s)`, a site
  must use at least one placeholder, unknown placeholders are refused.
- **Pre-filled** with DuckDuckGo, Amazon.fr and Fnac.
- No network request to build links. **POST** links are submitted by the browser (a hidden
  form, new tab), so the admin's login on that site is used when its session cookie allows
  it (`SameSite=None`; with the default `Lax` the site opens logged out). The **Try**
  button in Settings opens a site's search for a sample album to check this.

### Icons

- Found when a site is saved (or "Fetch icon again"): the icon URL if given, else the
  site's home page `<link rel="icon">`, else `/favicon.ico`.
- Converted to a 64 × 64 PNG (SVG refused), kept in `<data>/plugins/search-links/icons/`,
  served by our server (`/api/plugins/search-links/assets/icons/<site id>`).
- Fetching: `http(s)` only, local and private addresses refused (also after redirects),
  size limit, image content types only. A failure leaves the site without icon (a warning,
  the site is still saved).

## 3. Missing albums

- **Admins**: clicking an album the library does not have opens a popup: the enabled links
  of every plugin (by plugin, in the settings' order, with their icons), then "View on
  MusicBrainz". Links are fetched when the popup opens.
- **Other users**: the card links to MusicBrainz, as before. Owned albums link to our
  album page.

## 4. API (admins only)

| Method and path | Purpose |
|---|---|
| `GET /api/plugins` | Plugins: id, name, description, capabilities, fields, enabled, settings |
| `PUT /api/plugins/{id}` | `{ enabled, settings }`, validated; returns the plugin and warnings (e.g. icon not found) |
| `POST /api/plugins/{id}/try` | `{ settings, item }`: the links of one list row (saved or not) for a sample album |
| `GET /api/plugins/{id}/assets/{name}` | A plugin file (icons) |
| `GET /api/artists/{id}/discography/{mbid}/links` | Links of the enabled plugins for one release group of the artist's discography |

## 5. Out of scope

- Third-party plugins; the `download` capability.
- Logging in to sites from the server.
- Links for albums the library has.
