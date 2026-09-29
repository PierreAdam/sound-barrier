import { useEffect, useRef } from "react";

import type { InstallMethod } from "../pwa/install";
import { IosShareIcon } from "./Icons";

/** How to add the web UI to the home screen, when the browser has no prompt for it. */
export function InstallDialog({ method, onClose }: { method: Exclude<InstallMethod, "prompt" | null>; onClose(): void }) {
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  return (
    <dialog
      ref={dialog}
      className="install-dialog"
      aria-labelledby="install-dialog-title"
      onClose={onClose}
      // A tap outside the box (on the backdrop) closes it.
      onClick={(event) => event.target === dialog.current && dialog.current.close()}
    >
      <h2 id="install-dialog-title" className="install-dialog__title">
        Install as app
      </h2>
      <p className="text-muted">
        Sound-Barrier gets its icon on your home screen and opens full screen, without the browser's bars.
      </p>
      {method === "ios" ? (
        <ol className="install-dialog__steps">
          <li>
            Tap <strong>Share</strong> <IosShareIcon /> (Safari: at the bottom, or in the <strong>⋯</strong> menu).
          </li>
          <li>
            Choose <strong>Add to Home Screen</strong> (scroll the list down if needed).
          </li>
          <li>
            Keep <strong>Open as Web App</strong> on, then tap <strong>Add</strong>.
          </li>
        </ol>
      ) : (
        <ol className="install-dialog__steps">
          <li>
            Open the browser's menu (<strong>⋮</strong>).
          </li>
          <li>
            Choose <strong>Install app</strong> or <strong>Add to Home screen</strong>.
          </li>
        </ol>
      )}
      <p className="text-muted">You sign in once more in the app: it keeps its own session.</p>
      <div className="install-dialog__actions">
        <button className="button button--primary" type="button" onClick={() => dialog.current?.close()}>
          OK
        </button>
      </div>
    </dialog>
  );
}
