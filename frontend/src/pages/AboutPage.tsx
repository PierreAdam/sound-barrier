import { API_VERSION, CLIENT_NAME } from "../api/subsonic";
import { useSubsonic } from "../api/useSubsonic";
import { useSession } from "../auth/AuthContext";
import { setDiagnosticsOpen } from "../pwa/diagnostics";

export function AboutPage() {
  const { serverVersion } = useSession();
  const extensions = useSubsonic("getOpenSubsonicExtensions");

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
          <time dateTime={__BUILD_TIME__}>
            {new Date(__BUILD_TIME__).toLocaleString(undefined, { dateStyle: "long", timeStyle: "short" })}
          </time>
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
    </div>
  );
}
