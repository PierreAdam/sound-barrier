import { useEffect, useState } from "react";

import { api, type ServerLibrary, type ServerRuntime } from "../api/native";
import { API_VERSION, CLIENT_NAME } from "../api/subsonic";
import { useSubsonic } from "../api/useSubsonic";
import { useSession } from "../auth/AuthContext";
import { formatDuration, plural } from "../format";
import { setDiagnosticsOpen } from "../pwa/diagnostics";

type ServerDetails = { libraries: ServerLibrary[]; runtime: ServerRuntime | null };

// Kept for the session: what the server runs on does not change while you browse (only
// its uptime, advanced here from when it was asked).
let cached: { details: ServerDetails; at: number } | null = null;

const formatDate = (value: string) =>
  new Date(value).toLocaleString(undefined, { dateStyle: "long", timeStyle: "short" });

/** The browser, as it names itself (Chromium's brands, else the user agent string). */
function browserName(): string {
  const data = (navigator as Navigator & { userAgentData?: { brands: { brand: string; version: string }[]; platform: string } })
    .userAgentData;
  const brands = data?.brands.filter((b) => !/not.?a.?brand/i.test(b.brand)) ?? [];
  if (brands.length) {
    // The browser's own brand first (e.g. "Vivaldi", "Microsoft Edge"), then the engine.
    const own = brands.find((b) => !/^(Chromium|Google Chrome)$/.test(b.brand)) ?? brands[0]!;
    const engine = brands.find((b) => b.brand === "Chromium");
    return [`${own.brand} ${own.version}`, engine && engine !== own ? `Chromium ${engine.version}` : null, data?.platform]
      .filter(Boolean)
      .join(" · ");
  }
  return navigator.userAgent;
}

export function AboutPage() {
  const { serverVersion } = useSession();
  const extensions = useSubsonic("getOpenSubsonicExtensions");
  const [server, setServer] = useState<ServerDetails | null>(() => withUptime(cached));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cached) return;
    api
      .getAbout()
      .then((details) => {
        cached = { details, at: Date.now() };
        setServer(details);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="page">
      <h1 className="page__title">About</h1>
      <dl className="about">
        <dt>Server</dt>
        <dd>Sound-Barrier {serverVersion}</dd>
        <dt>Subsonic API</dt>
        <dd>{API_VERSION}</dd>
        <dt>Web client</dt>
        <dd>
          {CLIENT_NAME} {__APP_VERSION__}
        </dd>
        <dt>Built</dt>
        <dd>
          <time dateTime={__BUILD_TIME__}>{formatDate(__BUILD_TIME__)}</time>
        </dd>
        <dt>OpenSubsonic extensions</dt>
        <dd>
          {extensions.data?.openSubsonicExtensions
            .map((ext) => `${ext.name} (v${ext.versions.join(", v")})`)
            .join(" · ") ?? "…"}
        </dd>
      </dl>
      <p>
        <button className="button button--ghost" type="button" onClick={() => setDiagnosticsOpen(true)}>
          Display diagnostics
        </button>{" "}
        <span className="text-muted">Screen measurements, to report a layout problem on a phone.</span>
      </p>

      {error && <p className="text-error">The server's libraries and runtime could not be loaded: {error}</p>}
      {!server && !error && (
        <p className="about-loading text-muted" role="status">
          <span className="spinner" aria-hidden="true" /> Collecting the server's details…
        </p>
      )}
      {server?.runtime && <RuntimeSection runtime={server.runtime} />}

      <section className="about-section">
        <h2 className="about-section__title">Web client runtime</h2>
        <dl className="about">
          <dt>Browser</dt>
          <dd>{browserName()}</dd>
          <dt>Language</dt>
          <dd>{navigator.language}</dd>
          <dt>Time zone</dt>
          <dd>{Intl.DateTimeFormat().resolvedOptions().timeZone}</dd>
        </dl>
      </section>

      <section className="about-section">
        <h2 className="about-section__title">Libraries</h2>
        <p className="text-muted">
          What Sound-Barrier is built on, with their licenses. "Direct": declared by Sound-Barrier itself; the others are
          needed by those.
        </p>
        {server && (
          <LibraryTable
            title={`Server (Python): ${plural(server.libraries.length, "library", "libraries")}`}
            libraries={server.libraries.map((lib) => ({
              ...lib,
              url: lib.url ?? `https://pypi.org/project/${lib.name}/`,
            }))}
          />
        )}
        <LibraryTable
          title={`Web client (JavaScript): ${plural(__WEB_LIBRARIES__.length, "library", "libraries")}`}
          libraries={__WEB_LIBRARIES__.map((lib) => ({
            ...lib,
            summary: null,
            url: `https://www.npmjs.com/package/${lib.name}`,
          }))}
        />
      </section>
    </div>
  );
}

/** Admins: what the server runs on. */
function RuntimeSection({ runtime }: { runtime: ServerRuntime }) {
  return (
    <section className="about-section">
      <h2 className="about-section__title">Server runtime</h2>
      <dl className="about">
        <dt>Python</dt>
        <dd>{runtime.python}</dd>
        <dt>Operating system</dt>
        <dd>
          {runtime.os}
          {runtime.container ? " (Docker container)" : ""}
        </dd>
        <dt>Kernel</dt>
        <dd>
          {runtime.kernel} · {runtime.architecture}
          {runtime.cpus ? ` · ${plural(runtime.cpus, "CPU")}` : ""}
        </dd>
        <dt>Database</dt>
        <dd>{runtime.postgres ?? "unknown"}</dd>
        <dt>ffmpeg</dt>
        <dd>{runtime.ffmpeg ?? "not installed (no FLAC → MP3 conversion, no chapter editing in M4B files)"}</dd>
        <dt>Time zone</dt>
        <dd>{runtime.timeZone}</dd>
        <dt>Started</dt>
        <dd>
          <time dateTime={runtime.startedAt}>{formatDate(runtime.startedAt)}</time> (up {formatDuration(runtime.uptimeS)})
        </dd>
      </dl>
    </section>
  );
}

function LibraryTable({
  title,
  libraries,
}: {
  title: string;
  libraries: { name: string; version: string; license: string | null; summary: string | null; url: string | null; direct: boolean }[];
}) {
  return (
    <>
      <h3 className="about-section__subtitle">{title}</h3>
      <table className="users-table about-libraries">
        <thead>
          <tr>
            <th>Name</th>
            <th>Version</th>
            <th>License</th>
          </tr>
        </thead>
        <tbody>
          {libraries.map((lib) => (
            <tr key={lib.name}>
              <td title={lib.summary ?? undefined}>
                {lib.url ? (
                  <a className="link" href={lib.url} target="_blank" rel="noreferrer">
                    {lib.name}
                  </a>
                ) : (
                  lib.name
                )}
                {lib.direct && <span className="badge about-libraries__direct">direct</span>}
              </td>
              <td className="about-libraries__version">{lib.version}</td>
              <td>{lib.license ?? "?"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

/** The cached details, the server's uptime advanced by the time since they were asked. */
function withUptime(entry: typeof cached): ServerDetails | null {
  if (!entry) return null;
  const { details, at } = entry;
  if (!details.runtime) return details;
  return { ...details, runtime: { ...details.runtime, uptimeS: details.runtime.uptimeS + Math.round((Date.now() - at) / 1000) } };
}
