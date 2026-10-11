import type { MouseEvent } from "react";

/**
 * A modal <dialog>'s onClick: closes it on a click on the backdrop, outside its box. Such a
 * click targets the dialog itself, as one on its own padding does (between its fields):
 * only where it landed tells them apart.
 */
export function closeOnBackdropClick(event: MouseEvent<HTMLDialogElement>): void {
  const dialog = event.currentTarget;
  if (event.target !== dialog) return;
  const box = dialog.getBoundingClientRect();
  const inside =
    event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom;
  if (!inside) dialog.close();
}
