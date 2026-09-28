import { useState } from "react";

import { useSession } from "../auth/AuthContext";
import { MusicNoteIcon } from "./Icons";

interface Props {
  id?: string;
  /** Displayed size in CSS pixels; twice that is requested for sharp high-DPI screens. */
  size: number;
  alt?: string;
  className?: string;
}

export function CoverArt({ id, size, alt = "", className = "" }: Props) {
  const { client } = useSession();
  const [failedId, setFailedId] = useState<string | null>(null);
  const classes = `cover ${className}`.trim();

  if (!id || failedId === id) {
    return (
      <div className={`${classes} cover--placeholder`} aria-hidden={alt ? undefined : true}>
        <MusicNoteIcon />
      </div>
    );
  }
  return (
    <img
      className={classes}
      src={client.url("getCoverArt", { id, size: Math.min(size * 2, 1024) })}
      alt={alt}
      loading="lazy"
      onError={() => setFailedId(id)}
    />
  );
}
