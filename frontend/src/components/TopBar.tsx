import { useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { useSections } from "../api/useSections";
import { useAuth, useSession } from "../auth/AuthContext";
import { BrandLogo } from "./BrandLogo";
import { promptInstall, useInstallMethod } from "../pwa/install";
import { Dropdown } from "./Dropdown";
import { MenuIcon, UserIcon } from "./Icons";
import { InstallDialog } from "./InstallDialog";
import { SearchBox } from "./SearchBox";

const MUSIC_ITEMS = [
  { to: "/home", label: "Home" },
  { to: "/browse", label: "Browse" },
  { to: "/playlists", label: "Playlists" },
];
const SPOKEN_ITEMS = [
  { to: "/podcasts", label: "Podcasts", kind: "podcasts" },
  { to: "/audiobooks", label: "Audiobooks", kind: "audiobooks" },
] as const;
const ABOUT = { to: "/about", label: "About" };

/** The main links: Podcasts / Audiobooks only when an admin turned them on. */
function useNavItems() {
  const { sections } = useSections();
  return [...MUSIC_ITEMS, ...SPOKEN_ITEMS.filter((item) => sections[item.kind]), ABOUT];
}

/**
 * Brand, main links, search and the user menu. When the bar gets narrow (container
 * queries of .topbar in theme.less), the links collapse into one menu, then the user
 * name goes (the icon stays).
 */
export function TopBar({ onToggleMenu }: { onToggleMenu(): void }) {
  const navItems = useNavItems();
  return (
    <header className="topbar">
      <button className="icon-button topbar__menu" type="button" aria-label="Side panel" onClick={onToggleMenu}>
        <MenuIcon />
      </button>
      <div className="topbar__brand">
        <BrandLogo />
        <span>Sound-Barrier</span>
      </div>
      <nav className="topbar__nav" aria-label="Main">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `topbar__link${isActive ? " topbar__link--active" : ""}`}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <NavMenu />
      <div className="topbar__user">
        <SearchBox />
        <UserMenu />
      </div>
    </header>
  );
}

/** The main links in one menu (narrow bar), labelled with the current page. */
function NavMenu() {
  const location = useLocation();
  const navItems = useNavItems();
  const current = navItems.find((item) => location.pathname.startsWith(item.to));
  return (
    <Dropdown
      className="topbar__nav-menu"
      buttonClassName="topbar__link topbar__nav-button"
      label={`Pages (${current?.label ?? "menu"})`}
      button={
        <>
          {current?.label ?? "Menu"}
          <span className="topbar__chevron" aria-hidden>
            ▾
          </span>
        </>
      }
    >
      {(close) =>
        navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            role="menuitem"
            onClick={close}
            className={({ isActive }) => `dropdown__item${isActive ? " dropdown__item--active" : ""}`}
          >
            {item.label}
          </NavLink>
        ))
      }
    </Dropdown>
  );
}

/** Account, admin pages and signing out, behind the user name. */
function UserMenu() {
  const { logout } = useAuth();
  const { user } = useSession();
  // Phones and tablets, when not already opened from the home screen.
  const install = useInstallMethod();
  const [instructions, setInstructions] = useState<"ios" | "manual" | null>(null);

  async function onInstall() {
    if (install === "prompt" && (await promptInstall())) return;
    setInstructions(install === "ios" ? "ios" : "manual");
  }

  return (
    <>
      {instructions && <InstallDialog method={instructions} onClose={() => setInstructions(null)} />}
      <Dropdown
        buttonClassName="topbar__account"
        label={`${user.username}: account menu`}
        title={user.username}
        button={
          <>
            <UserIcon />
            <span className="topbar__username">{user.username}</span>
          </>
        }
      >
        {(close) => (
          <>
            <p className="dropdown__header">
              <span className="dropdown__name">{user.username}</span>
              {user.adminRole && <span className="badge">admin</span>}
            </p>
            <Link className="dropdown__item" role="menuitem" to="/account" onClick={close}>
              My account
            </Link>
            {user.adminRole && (
              <>
                <Link className="dropdown__item" role="menuitem" to="/settings" onClick={close}>
                  Settings
                </Link>
                <Link className="dropdown__item" role="menuitem" to="/manage" onClick={close}>
                  Library Management
                </Link>
              </>
            )}
            {install && (
              <button
                className="dropdown__item"
                type="button"
                role="menuitem"
                onClick={() => {
                  close();
                  void onInstall();
                }}
              >
                Install as app
              </button>
            )}
            <button
              className="dropdown__item dropdown__item--separated"
              type="button"
              role="menuitem"
              onClick={() => {
                close();
                logout();
              }}
            >
              Sign out
            </button>
          </>
        )}
      </Dropdown>
    </>
  );
}
