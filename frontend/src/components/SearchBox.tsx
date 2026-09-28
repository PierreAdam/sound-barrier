import { type FormEvent, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { SearchIcon } from "./Icons";

// While on the search page, results follow the typing after this pause.
const LIVE_DELAY_MS = 350;

/** The top bar's search field: Enter opens the search page, which then updates live. */
export function SearchBox() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const onSearchPage = location.pathname === "/search";
  const current = onSearchPage ? (params.get("q") ?? "") : "";
  const [text, setText] = useState(current);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Back / forward on the search page: the field shows the query of the page.
  useEffect(() => {
    if (onSearchPage) setText(current);
  }, [onSearchPage, current]);

  function go(query: string, replace: boolean) {
    navigate(`/search?q=${encodeURIComponent(query)}`, { replace });
  }

  function onChange(value: string) {
    setText(value);
    if (!onSearchPage) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => go(value.trim(), true), LIVE_DELAY_MS);
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (timer.current) clearTimeout(timer.current);
    if (text.trim()) go(text.trim(), onSearchPage);
  }

  return (
    <form className="search-box" role="search" onSubmit={onSubmit}>
      <SearchIcon />
      <input
        className="search-box__input"
        type="search"
        placeholder="Search"
        aria-label="Search artists, albums and songs"
        value={text}
        onChange={(e) => onChange(e.target.value)}
      />
    </form>
  );
}
