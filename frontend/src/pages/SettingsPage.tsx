import { Navigate, useSearchParams } from "react-router-dom";

import { useSession } from "../auth/AuthContext";
import { ExternalSection } from "./settings/ExternalSection";
import { ImportSection } from "./settings/ImportSection";
import { LibrarySection } from "./settings/LibrarySection";
import { PluginsSection } from "./settings/PluginsSection";
import { ScheduleSection } from "./settings/ScheduleSection";
import { SpokenSection } from "./settings/SpokenSection";
import { SETTINGS_TABS as TABS } from "./settings/tabs";
import { TranscriptsSection } from "./settings/TranscriptsSection";
import { UsersSection } from "./settings/UsersSection";

/**
 * Server settings, for admins only (personal settings are on the account page), one tab
 * per topic. The tab is in the URL, so links and reloads open the right one.
 */
export function SettingsPage() {
  const { user } = useSession();
  const [params, setParams] = useSearchParams();
  if (!user.adminRole) return <Navigate to="/account" replace />;
  const tab = TABS.find((t) => t.id === params.get("tab"))?.id ?? "library";

  return (
    <div className="page settings">
      <h1 className="page__title">Settings</h1>
      <nav className="tabs" role="tablist" aria-label="Settings">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`tabs__tab${tab === t.id ? " tabs__tab--active" : ""}`}
            onClick={() => setParams({ tab: t.id }, { replace: true })}
          >
            {t.label}
          </button>
        ))}
      </nav>
      {tab === "library" && (
        <>
          <LibrarySection />
          <SpokenSection />
          <ScheduleSection />
        </>
      )}
      {tab === "import" && <ImportSection />}
      {tab === "external" && <ExternalSection />}
      {tab === "album-search" && <PluginsSection />}
      {tab === "transcripts" && <TranscriptsSection />}
      {tab === "users" && <UsersSection />}
    </div>
  );
}
