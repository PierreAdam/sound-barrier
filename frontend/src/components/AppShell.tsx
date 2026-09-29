import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useLibraryWatcher } from "../api/useLibraryWatcher";
import { SectionsProvider } from "../api/useSections";
import { useAuth } from "../auth/AuthContext";
import { PlayerProvider } from "../player/PlayerContext";
import { PreferencesProvider } from "../preferences/PreferencesContext";
import { NowPlaying, NowPlayingProvider } from "./NowPlaying";
import { PlayerDock } from "./PlayerDock";
import { SidePanel } from "./SidePanel";
import { TopBar } from "./TopBar";

/** Main layout: top bar, side panel, page content and the always-visible player bar. */
export function AppShell() {
  const { session, restoring } = useAuth();
  const location = useLocation();
  // On narrow screens the side panel is a drawer opened from the top bar.
  const [panelOpen, setPanelOpen] = useState(false);
  useEffect(() => setPanelOpen(false), [location.pathname]);

  if (restoring) return <div className="splash">Loading…</div>;
  if (!session) return <Navigate to="/login" replace />;

  return (
    <PreferencesProvider>
      <SectionsProvider>
        <PlayerProvider>
          <NowPlayingProvider>
            <LibraryWatcher />
            <div className={`app${panelOpen ? " app--panel-open" : ""}`}>
              <TopBar onToggleMenu={() => setPanelOpen((open) => !open)} />
              <div className="app__body">
                <SidePanel />
                {panelOpen && <div className="app__backdrop" onClick={() => setPanelOpen(false)} />}
                <main className="app__content">
                  <Outlet />
                </main>
              </div>
              <NowPlaying />
              <PlayerDock />
            </div>
          </NowPlayingProvider>
        </PlayerProvider>
      </SectionsProvider>
    </PreferencesProvider>
  );
}

/** Mounted only while signed in (the revision needs a session). */
function LibraryWatcher() {
  useLibraryWatcher();
  return null;
}
