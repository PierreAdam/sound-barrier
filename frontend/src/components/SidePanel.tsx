import { NavLink } from "react-router-dom";

import { useSubsonic } from "../api/useSubsonic";
import { useSession } from "../auth/AuthContext";
import { LibraryIcon } from "./Icons";

/** DOM id of a letter group in the side panel ("#" is not usable in an id selector). */
function letterId(letter: string): string {
  return `side-letter-${letter === "#" ? "other" : letter}`;
}

/**
 * Left panel: the artist index (like Subsonic), with letters to jump to. Admins also get
 * Library Management on top (often needed); Settings stay in the user menu.
 */
export function SidePanel() {
  const { data, error } = useSubsonic("getArtists");
  const index = data?.artists.index ?? [];
  const { user } = useSession();

  return (
    <aside className="sidepanel">
      {user.adminRole && (
        <nav className="sidepanel__pages" aria-label="Pages">
          <NavLink to="/manage" className={({ isActive }) => `sidepanel__page${isActive ? " sidepanel__page--active" : ""}`}>
            <LibraryIcon />
            <span>Library Management</span>
          </NavLink>
        </nav>
      )}
      <div className="sidepanel__artists" aria-label="Artists">
        {error && <p className="text-error sidepanel__message">{error.message}</p>}
        {data && index.length === 0 && <p className="text-muted sidepanel__message">No artists yet.</p>}
        {index.map((group) => (
          <section key={group.name} id={letterId(group.name)} className="side-index">
            <h2 className="side-index__letter">{group.name}</h2>
            <ul className="side-index__list">
              {group.artist.map((artist) => (
                <li key={artist.id}>
                  <NavLink
                    to={`/artists/${artist.id}`}
                    className={({ isActive }) => `side-index__artist${isActive ? " side-index__artist--active" : ""}`}
                  >
                    {artist.name}
                  </NavLink>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      {index.length > 0 && (
        <nav className="sidepanel__letters" aria-label="Jump to letter">
          {index.map((group) => (
            <button
              key={group.name}
              type="button"
              className="sidepanel__letter"
              onClick={() => document.getElementById(letterId(group.name))?.scrollIntoView({ block: "start" })}
            >
              {group.name}
            </button>
          ))}
        </nav>
      )}
    </aside>
  );
}
