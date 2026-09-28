import { NavLink } from "react-router-dom";

import { useAuth, useSession } from "../auth/AuthContext";
import { BrandLogo } from "./BrandLogo";
import { MenuIcon, UserIcon } from "./Icons";
import { SearchBox } from "./SearchBox";

const NAV_ITEMS = [
  { to: "/home", label: "Home" },
  { to: "/browse", label: "Browse" },
  { to: "/playlists", label: "Playlists" },
  { to: "/about", label: "About" },
];

export function TopBar({ onToggleMenu }: { onToggleMenu(): void }) {
  const { logout } = useAuth();
  const { user } = useSession();

  return (
    <header className="topbar">
      <button className="icon-button topbar__menu" type="button" aria-label="Menu" onClick={onToggleMenu}>
        <MenuIcon />
      </button>
      <div className="topbar__brand">
        <BrandLogo />
        <span>Sound-Barrier</span>
      </div>
      <nav className="topbar__nav" aria-label="Main">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `topbar__link${isActive ? " topbar__link--active" : ""}`}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="topbar__user">
        <SearchBox />
        <NavLink
          to="/account"
          title="My account"
          className={({ isActive }) => `topbar__account${isActive ? " topbar__account--active" : ""}`}
        >
          <UserIcon />
          <span className="topbar__username">{user.username}</span>
        </NavLink>
        {user.adminRole && <span className="badge">admin</span>}
        <button className="button button--ghost" type="button" onClick={logout}>
          Sign out
        </button>
      </div>
    </header>
  );
}
