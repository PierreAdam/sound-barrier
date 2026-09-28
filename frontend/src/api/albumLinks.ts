import type { AlbumLink } from "./native";

/**
 * Opens a link in a new tab. POST links are a form the browser submits itself, so the
 * user's login on that site is used (when its cookies allow it).
 */
export function openAlbumLink(link: AlbumLink): void {
  if (link.method === "GET") {
    window.open(link.url, "_blank", "noopener,noreferrer");
    return;
  }
  const form = document.createElement("form");
  form.method = "post";
  form.action = link.url;
  form.target = "_blank";
  form.rel = "noopener noreferrer";
  form.style.display = "none";
  for (const [name, value] of link.form) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }
  document.body.appendChild(form);
  form.submit();
  form.remove();
}
