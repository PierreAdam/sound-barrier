import { type FormEvent, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import { type AudibleBook, api, type SpokenDetails, type SpokenFileDetails, type SpokenKind } from "../api/native";
import { useSession } from "../auth/AuthContext";
import { formatDuration, formatTime } from "../format";
import { applyAudible } from "./audibleChapters";

/**
 * Admins: a book's / show's details after the import (the same fields as the import
 * review), written into its files' tags. A new title or author renames its folder too.
 */
export function SpokenDetailsPage({ kind }: { kind: SpokenKind }) {
  const { id = "" } = useParams();
  const { user } = useSession();
  const navigate = useNavigate();
  const [details, setDetails] = useState<SpokenDetails | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const book = kind === "audiobooks";

  useEffect(() => {
    if (!user.adminRole) return;
    api
      .getSpokenDetails(id)
      .then(setDetails)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [id, user.adminRole]);

  if (!user.adminRole) return <Navigate to={`/${kind}/${id}`} replace />;
  if (!details) return error ? <p className="text-error">{error}</p> : <p className="text-muted">Loading…</p>;

  function set(update: Partial<SpokenDetails>) {
    setDetails((current) => (current ? { ...current, ...update } : current));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!details) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api.setSpokenDetails(id, details);
      navigate(`/${kind}/${saved.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="page tag-editor">
      <div className="page__header">
        <h1 className="page__title">Edit details</h1>
        <Link className="link" to={`/${kind}/${id}`}>
          Back to the {book ? "book" : "show"}
        </Link>
      </div>
      <p className="text-muted">
        Written into the {book ? "book's" : "show's"} files: every Subsonic app sees the change too. A new{" "}
        {book ? "title or author" : "title"} also renames its folder ({book ? "Author / Title" : "Show"}), as the import
        does; bookmarks and plays follow.
      </p>

      <form className="tag-editor__form" onSubmit={(e) => void save(e)}>
        <div className="tag-editor__album">
          <label className="field">
            <span className="field__label">{book ? "Title" : "Show"}</span>
            <input className="field__input" value={details.title} required onChange={(e) => set({ title: e.target.value })} />
          </label>
          <label className="field">
            <span className="field__label">{book ? "Author" : "Host / publisher"}</span>
            <input
              className="field__input"
              value={details.author}
              required={book}
              onChange={(e) => set({ author: e.target.value })}
            />
          </label>
          {book && (
            <>
              <label className="field">
                <span className="field__label">Narrator</span>
                <input
                  className="field__input"
                  value={details.narrator ?? ""}
                  onChange={(e) => set({ narrator: e.target.value || null })}
                />
              </label>
              <label className="field">
                <span className="field__label">Series</span>
                <input
                  className="field__input"
                  value={details.series ?? ""}
                  placeholder="None"
                  onChange={(e) => set({ series: e.target.value || null })}
                />
              </label>
              <label className="field tag-editor__short">
                <span className="field__label">Book</span>
                <input
                  className="field__input"
                  inputMode="decimal"
                  value={details.seriesNumber ?? ""}
                  placeholder="#"
                  disabled={!details.series}
                  onChange={(e) => set({ seriesNumber: e.target.value || null })}
                />
              </label>
              <label className="field tag-editor__short">
                <span className="field__label">Year</span>
                <input
                  className="field__input"
                  inputMode="numeric"
                  value={details.year ?? ""}
                  onChange={(e) => {
                    const year = Number.parseInt(e.target.value, 10);
                    set({ year: Number.isFinite(year) ? year : null });
                  }}
                />
              </label>
            </>
          )}
          <label className="field">
            <span className="field__label">Genre</span>
            <input className="field__input" value={details.genre ?? ""} onChange={(e) => set({ genre: e.target.value || null })} />
          </label>
        </div>
        <label className="field">
          <span className="field__label">Description</span>
          <textarea
            className="field__input spoken-details__description"
            rows={8}
            maxLength={10_000}
            value={details.description ?? ""}
            onChange={(e) => set({ description: e.target.value || null })}
          />
        </label>
        {details.files && details.files.length > 0 && (
          <ChaptersEditor
            book={book}
            title={details.title}
            author={details.author}
            files={details.files}
            onChange={(files) => set({ files })}
          />
        )}
        {error && <p className="text-error">{error}</p>}
        <div className="settings-section__actions">
          <button className="button button--primary" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save the details"}
          </button>
        </div>
      </form>
    </div>
  );
}

/**
 * The files of the book and the chapters inside them: titles to edit, and "Look up on
 * Audible" to fill them from Audible's chapter list.
 */
function ChaptersEditor({
  book,
  title,
  author,
  files,
  onChange,
}: {
  book: boolean;
  title: string;
  author: string;
  files: SpokenFileDetails[];
  onChange(files: SpokenFileDetails[]): void;
}) {
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const several = files.length > 1;

  function setFile(index: number, update: Partial<SpokenFileDetails>) {
    onChange(files.map((f, i) => (i === index ? { ...f, ...update } : f)));
  }

  function setChapter(fileIndex: number, chapterIndex: number, text: string) {
    const file = files[fileIndex]!;
    setFile(fileIndex, {
      chapters: (file.chapters ?? []).map((c, i) => (i === chapterIndex ? { ...c, title: text } : c)),
    });
  }

  return (
    <section className="spoken-details__chapters" aria-label="Chapters">
      <div className="spoken-details__chapters-header">
        <h2 className="settings-section__title">{several ? "Files and chapters" : "Chapters"}</h2>
        {book && (
          <AudibleLookup
            title={title}
            author={author}
            onChapters={(chapters) => {
              const applied = applyAudible(files, chapters);
              if ("error" in applied) setNotice({ ok: false, text: applied.error });
              else {
                onChange(applied.files);
                setNotice({ ok: true, text: applied.message });
              }
            }}
          />
        )}
      </div>
      {notice && <p className={notice.ok ? "text-success" : "text-error"}>{notice.text}</p>}
      {files.map((file, fileIndex) => (
        <div key={file.id} className="spoken-details__file">
          {several && (
            <label className="field spoken-details__file-title">
              <span className="field__label">
                {fileIndex + 1}. <span className="text-muted">{file.fileName} · {formatDuration(file.durationMs / 1000)}</span>
              </span>
              <input className="field__input" value={file.title} required onChange={(e) => setFile(fileIndex, { title: e.target.value })} />
            </label>
          )}
          {file.chapters && file.chapters.length > 0 ? (
            <ol className="spoken-details__chapter-list">
              {file.chapters.map((chapter, chapterIndex) => (
                <li key={chapter.startMs}>
                  <span className="text-muted spoken-details__time">{formatTime(chapter.startMs / 1000)}</span>
                  <input
                    className="field__input"
                    aria-label={`Chapter at ${formatTime(chapter.startMs / 1000)}`}
                    value={chapter.title}
                    onChange={(e) => setChapter(fileIndex, chapterIndex, e.target.value)}
                  />
                </li>
              ))}
            </ol>
          ) : (
            !several && (
              <p className="text-muted">
                No chapters inside this file.{book && file.canWriteChapters ? " Audible's can be added (Look up on Audible)." : ""}
              </p>
            )
          )}
        </div>
      ))}
    </section>
  );
}

/** Finds the book on Audible (by title and author) and gets its chapter list. */
function AudibleLookup({
  title,
  author,
  onChapters,
}: {
  title: string;
  author: string;
  onChapters(chapters: Awaited<ReturnType<typeof api.getAudibleChapters>>): void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(title);
  const [results, setResults] = useState<AudibleBook[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search() {
    setBusy(true);
    setError(null);
    try {
      // The author narrows the search of the book's own title; other words are searched alone.
      const sameTitle = query.trim().toLowerCase() === title.trim().toLowerCase();
      setResults(await api.searchAudible(query, sameTitle && author ? author : undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function choose(result: AudibleBook) {
    setBusy(true);
    setError(null);
    try {
      onChapters(await api.getAudibleChapters(result.asin));
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        className="button button--ghost"
        type="button"
        onClick={() => {
          setOpen(true);
          setQuery(title);
          void search();
        }}
      >
        Look up on Audible
      </button>
    );
  }
  return (
    <div className="audible-lookup">
      <div className="folder-form__row">
        <input
          className="field__input"
          aria-label="Search Audible"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void search();
            }
          }}
        />
        <button className="button" type="button" disabled={busy || !query.trim()} onClick={() => void search()}>
          Search
        </button>
        <button className="button button--ghost" type="button" onClick={() => setOpen(false)}>
          Close
        </button>
      </div>
      {error && <p className="text-error">{error}</p>}
      {busy && <p className="text-muted">Asking Audible…</p>}
      {results && results.length === 0 && <p className="text-muted">Nothing found: try other words.</p>}
      {results && results.length > 0 && (
        <ul className="audible-lookup__results">
          {results.map((result) => (
            <li key={result.asin}>
              <button className="audible-lookup__result" type="button" disabled={busy} onClick={() => void choose(result)}>
                <strong>{result.title}</strong>
                <span className="text-muted">
                  {[
                    result.authors.join(", "),
                    result.series && `${result.series}${result.seriesNumber ? ` #${result.seriesNumber}` : ""}`,
                    result.narrators.length ? `read by ${result.narrators.join(", ")}` : null,
                    result.durationMs ? formatDuration(result.durationMs / 1000) : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
