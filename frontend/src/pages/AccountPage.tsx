import { useSession } from "../auth/AuthContext";
import { AppearanceSection } from "./account/AppearanceSection";
import { PasswordSection } from "./account/PasswordSection";
import { PlayerSection } from "./account/PlayerSection";

/** The signed-in user's own page (opened from the username in the top bar). */
export function AccountPage() {
  const { user } = useSession();
  return (
    <div className="page settings">
      <div className="page__header">
        <h1 className="page__title">My account</h1>
        <span className="text-muted">{user.username}</span>
        {user.adminRole && <span className="badge">admin</span>}
      </div>
      <AppearanceSection />
      <PlayerSection />
      <PasswordSection />
    </div>
  );
}
