import { Navigate } from "react-router-dom";

import { useSession } from "../auth/AuthContext";
import { ExternalSection } from "./settings/ExternalSection";
import { ImportSection } from "./settings/ImportSection";
import { LibrarySection } from "./settings/LibrarySection";
import { ScheduleSection } from "./settings/ScheduleSection";
import { UsersSection } from "./settings/UsersSection";

/** Server settings, for admins only (personal settings are on the account page). */
export function SettingsPage() {
  const { user } = useSession();
  if (!user.adminRole) return <Navigate to="/account" replace />;
  return (
    <div className="page settings">
      <h1 className="page__title">Settings</h1>
      <LibrarySection />
      <ImportSection />
      <ScheduleSection />
      <ExternalSection />
      <UsersSection />
    </div>
  );
}
