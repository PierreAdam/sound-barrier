import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";

import { api, type ManageSettings } from "../api/native";
import { useSession } from "../auth/AuthContext";
import { DeleteTab } from "./manage/DeleteTab";
import { ImportTab } from "./manage/ImportTab";
import { LibraryTab } from "./manage/LibraryTab";
import { NewReleasesTab } from "./manage/NewReleasesTab";
import { ReviewTab } from "./manage/ReviewTab";
import { useImports } from "./manage/useImports";

type Tab = "library" | "import" | "review" | "delete" | "new-releases";

/**
 * Admins: library status and beets maintenance, import new music, review album matches,
 * delete music, new releases of the library's artists.
 */
export function ManageLibraryPage() {
  const { user } = useSession();
  const [tab, setTab] = useState<Tab>("library");
  const [settings, setSettings] = useState<ManageSettings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const imports = useImports();

  useEffect(() => {
    api
      .getManageSettings()
      .then(setSettings)
      .catch((e: unknown) => setSettingsError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (!user.adminRole) return <Navigate to="/home" replace />;

  const reviewCount = imports.review.length;
  const tabs: { id: Tab; label: string }[] = [
    { id: "library", label: "Library" },
    { id: "import", label: "Import" },
    { id: "review", label: reviewCount ? `Review (${reviewCount})` : "Review" },
    { id: "delete", label: "Delete" },
    { id: "new-releases", label: "New releases" },
  ];

  return (
    <div className="page manage">
      <div className="page__header">
        <h1 className="page__title">Manage Library</h1>
        {settings && <span className="text-muted">Tagging: {settings.tagger}</span>}
      </div>
      {settings && !settings.matching && (
        <p className="notice">
          MusicBrainz matching (beets) is not integrated yet: albums are imported with the tags they already have.
        </p>
      )}
      {settingsError && <p className="text-error">{settingsError}</p>}

      <nav className="tabs" role="tablist" aria-label="Manage Library">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`tabs__tab${tab === t.id ? " tabs__tab--active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "library" && <LibraryTab imports={imports} onReview={() => setTab("review")} />}
      {tab === "import" && settings && (
        <ImportTab settings={settings} imports={imports} onReview={() => setTab("review")} />
      )}
      {tab === "review" && (
        <ReviewTab
          imports={imports}
          matching={settings?.matching ?? false}
          convertLossless={settings?.transcodeLossless ?? false}
        />
      )}
      {tab === "delete" && <DeleteTab />}
      {tab === "new-releases" && <NewReleasesTab />}
    </div>
  );
}
