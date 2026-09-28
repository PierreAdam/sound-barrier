// Small inline SVG icons (no icon library). They inherit the text color.
import type { ReactNode } from "react";

function Icon({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? "img" : undefined}
    >
      {children}
    </svg>
  );
}

export const PlayIcon = () => (
  <Icon>
    <path d="M8 5v14l11-7z" />
  </Icon>
);

export const PauseIcon = () => (
  <Icon>
    <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
  </Icon>
);

export const PreviousIcon = () => (
  <Icon>
    <path d="M6 6h2v12H6zM9.5 12 18 18V6z" />
  </Icon>
);

export const NextIcon = () => (
  <Icon>
    <path d="M16 6h2v12h-2zM6 18l8.5-6L6 6z" />
  </Icon>
);

export const VolumeIcon = ({ muted }: { muted: boolean }) => (
  <Icon>
    <path d="M4 9v6h4l5 5V4L8 9z" />
    {muted ? (
      <path d="m16 9 5 5m0-5-5 5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    ) : (
      <path d="M16 8.5a4.5 4.5 0 0 1 0 7M18.5 6a8 8 0 0 1 0 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    )}
  </Icon>
);

export const FolderIcon = () => (
  <Icon>
    <path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
  </Icon>
);

export const RefreshIcon = () => (
  <Icon>
    <path
      d="M20 12a8 8 0 1 1-2.34-5.66M20 4v5h-5"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Icon>
);

export const MusicNoteIcon = () => (
  <Icon>
    <path d="M9 17.5A2.5 2.5 0 1 1 6.5 15H9V5l10-2v12.5a2.5 2.5 0 1 1-2.5-2.5H19V6.4l-8 1.6v9.5z" />
  </Icon>
);

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

export const ShuffleIcon = () => (
  <Icon>
    <path {...stroke} d="M3 7h3.5c2 0 3.2 1 4.3 2.6l2.4 4.8c1.1 1.6 2.3 2.6 4.3 2.6H21M17 13.5 21 17l-4 3.5M3 17h3.5c1.3 0 2.2-.4 3-1.1M13.5 8.1c.8-.7 1.7-1.1 3-1.1H21M17 3.5 21 7l-4 3.5" />
  </Icon>
);

export const RepeatIcon = ({ one = false }: { one?: boolean }) => (
  <Icon>
    <path {...stroke} d="M17 3l3 3-3 3M4 11V9a3 3 0 0 1 3-3h13M7 21l-3-3 3-3M20 13v2a3 3 0 0 1-3 3H4" />
    {one && <path d="M11 10.5h1.6V15H11z" />}
  </Icon>
);

export const CrossfadeIcon = () => (
  <Icon>
    <path {...stroke} d="M3 18c4 0 6-12 9-12s5 12 9 12M3 6c4 0 6 12 9 12s5-12 9-12" />
  </Icon>
);

export const SettingsIcon = () => (
  <Icon>
    <path
      {...stroke}
      d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"
    />
  </Icon>
);

export const InfoIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="9" {...stroke} />
    <path {...stroke} d="M12 11v5M12 8h.01" />
  </Icon>
);

export const MenuIcon = () => (
  <Icon>
    <path {...stroke} d="M4 6h16M4 12h16M4 18h16" />
  </Icon>
);

export const PlaylistIcon = () => (
  <Icon>
    <path {...stroke} d="M4 6h11M4 11h11M4 16h7M17 13v6m-3-3h6" />
  </Icon>
);

export const SearchIcon = () => (
  <Icon>
    <path {...stroke} d="M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM20 20l-4.8-4.8" />
  </Icon>
);

export const EditIcon = () => (
  <Icon>
    <path {...stroke} d="M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4" />
  </Icon>
);

export const AddIcon = () => (
  <Icon>
    <path {...stroke} d="M12 5v14M5 12h14" />
  </Icon>
);

export const PlayNextIcon = () => (
  <Icon>
    <path {...stroke} d="M5 12h13M13 6l6 6-6 6" />
  </Icon>
);

export const QueueIcon = () => (
  <Icon>
    <path {...stroke} d="M4 6h12M4 12h12M4 18h8M17 15v6l4-3z" />
  </Icon>
);

export const RemoveIcon = () => (
  <Icon>
    <path {...stroke} d="M6 6l12 12M18 6 6 18" />
  </Icon>
);

export const UndoIcon = () => (
  <Icon>
    <path {...stroke} d="M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3" />
  </Icon>
);

export const TrashIcon = () => (
  <Icon>
    <path {...stroke} d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
  </Icon>
);


export const UserIcon = () => (
  <Icon>
    <circle cx="12" cy="8" r="4" {...stroke} />
    <path {...stroke} d="M4 21a8 8 0 0 1 16 0" />
  </Icon>
);

export const LibraryIcon = () => (
  <Icon>
    <path {...stroke} d="M4 4v16M9 4v16M14 5l5 15M3 20h18" />
  </Icon>
);

/** A record: an artist's discography. */
export const DiscIcon = () => (
  <Icon>
    <path
      fillRule="evenodd"
      d="M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zm0 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm0 5a3 3 0 1 1 0 6 3 3 0 0 1 0-6z"
    />
  </Icon>
);
