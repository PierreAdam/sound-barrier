import { type FormEvent, useCallback, useEffect, useState } from "react";

import { api, type TranscriptBook, type TranscriptFile, type TranscriptWork, type WorkerToken } from "../../api/native";
import { formatDuration, plural } from "../../format";
import { listPage } from "./transcriptList";

const REFRESH_MS = 5000;
const KIND_LABELS = { podcasts: "Podcast", audiobooks: "Audiobook" } as const;

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "never";
}

/**
 * Admins: speech to text of podcasts and audiobooks. The recognition runs on a PC with a
 * GPU (the companion app, `transcriber/` in the repository), signed in with a worker token.
 */
export function TranscriptsSection() {
  const [tokens, setTokens] = useState<WorkerToken[]>([]);
  const [books, setBooks] = useState<TranscriptBook[]>([]);
  const [working, setWorking] = useState<TranscriptWork[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [found, overview] = await Promise.all([api.getWorkerTokens(), api.getTranscripts()]);
      setTokens(found);
      setBooks(overview.books);
      setWorking(overview.working);
      setError(null);
    } catch (e) {
      setError(message(e));
    }
  }, []);

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void reload();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  return (
    <>
      <WorkersSection tokens={tokens} onChange={reload} />
      {error && <p className="text-error">{error}</p>}
      <section className="settings-section settings-section--wide">
        <h2 className="settings-section__title">Transcribing now</h2>
        {working.length === 0 ? (
          <p className="text-muted">No worker is transcribing right now.</p>
        ) : (
          <ul className="transcripts-working">
            {working.map((work) => (
              <li key={work.songId}>
                <div className="transcripts-working__row">
                  <span>
                    <strong>{work.book}</strong> · {work.title}
                  </span>
                  <span className="text-muted">
                    {work.worker} · {Math.round(work.progress * 100)} %
                  </span>
                </div>
                <div className="meter" aria-hidden="true">
                  <div className="meter__fill" style={{ width: `${work.progress * 100}%` }} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <BooksSection books={books} onChange={reload} />
    </>
  );
}

function WorkersSection({ tokens, onChange }: { tokens: WorkerToken[]; onChange(): Promise<void> }) {
  const [name, setName] = useState("");
  const [created, setCreated] = useState<{
    name: string;
    secret: string;
  } | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const { token, secret } = await api.createWorkerToken(name.trim());
      setCreated({ name: token.name, secret });
      setCopied(false);
      setName("");
      await onChange();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(token: WorkerToken) {
    if (
      !window.confirm(
        `Revoke "${token.name}"? The app using it can no longer connect; its files in progress wait again.`,
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await api.revokeWorkerToken(token.id);
      await onChange();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function copy(secret: string) {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
    } catch {
      setError("Cannot copy: select the token and copy it by hand.");
    }
  }

  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">Transcription workers</h2>
      <p className="text-muted">
        Podcasts and audiobooks can get their text, shown like synced lyrics in "Now playing" and in the Subsonic apps.
        The speech recognition runs on a PC with an NVIDIA GPU, with the companion app (<code>transcriber/</code> in the
        Sound-Barrier repository): it connects to this server with a token, takes the files that have no text yet, and
        sends the text back. The server never connects to the PC. The text is also written as a <code>.lrc</code> file
        next to the audio (never replacing a <code>.lrc</code> it did not write).
      </p>
      <p className="text-muted">
        A token only lets the app list, download and transcribe podcasts and audiobooks: it cannot sign in to the web UI
        or the Subsonic API.
      </p>

      {tokens.length > 0 && (
        <table className="users-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Created</th>
              <th>Last used</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {tokens.map((token) => (
              <tr key={token.id}>
                <td>{token.name}</td>
                <td className="text-muted">{when(token.createdAt)}</td>
                <td className="text-muted">{when(token.lastUsedAt)}</td>
                <td className="users-table__actions">
                  <button
                    className="button button--ghost button--danger"
                    type="button"
                    disabled={busy}
                    onClick={() => void revoke(token)}
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {created && (
        <div className="token-created">
          <p>
            Token for <strong>{created.name}</strong>. Copy it now: it is not shown again.
          </p>
          <div className="folder-form__row">
            <input
              className="field__input token-created__secret"
              readOnly
              value={created.secret}
              onFocus={(e) => e.target.select()}
              aria-label="New worker token"
            />
            <button className="button button--primary" type="button" onClick={() => void copy(created.secret)}>
              {copied ? "Copied" : "Copy"}
            </button>
            <button className="button button--ghost" type="button" onClick={() => setCreated(null)}>
              Done
            </button>
          </div>
          <p className="text-muted">
            On the PC, in the <code>transcriber</code> folder: <code>transcriber login {window.location.origin}</code>,
            then paste the token.
          </p>
        </div>
      )}

      <form className="folder-form" onSubmit={(e) => void create(e)}>
        <label className="field">
          <span className="field__label">New token</span>
          <div className="folder-form__row">
            <input
              className="field__input"
              placeholder="A name for the PC, e.g. Desktop"
              maxLength={60}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <button className="button button--primary" type="submit" disabled={busy || !name.trim()}>
              Create
            </button>
          </div>
        </label>
      </form>
      {error && <p className="text-error">{error}</p>}
    </section>
  );
}

/** The podcasts and audiobooks: searched, by default only those still missing text, 10 a page. */
function BooksSection({ books, onChange }: { books: TranscriptBook[]; onChange(): Promise<void> }) {
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [withoutText, setWithoutText] = useState(true);
  const [page, setPage] = useState(1);
  // Kept in range by listPage (the list changes as files get their text).
  const shown = listPage(books, { query, withoutText, page });

  async function run(operation: () => Promise<unknown>) {
    setError(null);
    try {
      await operation();
      await onChange();
    } catch (e) {
      setError(message(e));
    }
  }

  function remove(book: TranscriptBook) {
    if (
      !window.confirm(
        `Remove the text of "${book.title}"? Its .lrc files written by the transcriber go too; it can be transcribed again.`,
      )
    ) {
      return;
    }
    void run(() => api.removeTranscripts(book.id));
  }

  const total = books.reduce((sum, b) => sum + b.files, 0);
  const done = books.reduce((sum, b) => sum + b.done, 0);

  return (
    <section className="settings-section settings-section--wide">
      <h2 className="settings-section__title">Podcasts and audiobooks</h2>
      {books.length === 0 ? (
        <p className="text-muted">No podcasts or audiobooks (turn them on in Settings → Library).</p>
      ) : (
        <>
          <p className="text-muted">
            {done} of {plural(total, "file")} have their text.
          </p>
          {error && <p className="text-error">{error}</p>}
          <div className="transcripts-list__tools">
            <input
              className="field__input transcripts-list__search"
              type="search"
              placeholder="Search a title or an author"
              aria-label="Search the podcasts and audiobooks"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(1);
              }}
            />
            <label className="checkbox">
              <input
                type="checkbox"
                checked={withoutText}
                onChange={(e) => {
                  setWithoutText(e.target.checked);
                  setPage(1);
                }}
              />
              Without transcript
            </label>
          </div>
          {shown.matching === 0 ? (
            <p className="text-muted">
              {query.trim()
                ? `Nothing matches “${query.trim()}”${withoutText ? " among those without transcript" : ""}.`
                : "Every podcast and audiobook has its text."}
            </p>
          ) : (
            <table className="users-table transcripts-table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Length</th>
                  <th>Text</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {shown.books.map((book) => (
                  <BookRow
                    key={book.id}
                    book={book}
                    open={open === book.id}
                    onToggle={() => setOpen(open === book.id ? null : book.id)}
                    onRetry={() => void run(() => api.retryTranscripts(book.id))}
                    onRemove={() => remove(book)}
                  />
                ))}
              </tbody>
            </table>
          )}
          {shown.pages > 1 && (
            <nav className="pagination" aria-label="Pages">
              <button
                className="button button--ghost"
                type="button"
                disabled={shown.page <= 1}
                onClick={() => setPage(shown.page - 1)}
              >
                Previous
              </button>
              <span className="text-muted">
                Page {shown.page} of {shown.pages} · {plural(shown.matching, "entry", "entries")}
              </span>
              <button
                className="button button--ghost"
                type="button"
                disabled={shown.page >= shown.pages}
                onClick={() => setPage(shown.page + 1)}
              >
                Next
              </button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}

function status(book: TranscriptBook): string {
  const parts = [`${book.done} / ${book.files}`];
  if (book.working) parts.push(`${book.working} in progress`);
  if (book.failed) parts.push(`${book.failed} failed`);
  return parts.join(" · ");
}

function BookRow({
  book,
  open,
  onToggle,
  onRetry,
  onRemove,
}: {
  book: TranscriptBook;
  open: boolean;
  onToggle(): void;
  onRetry(): void;
  onRemove(): void;
}) {
  const [files, setFiles] = useState<TranscriptFile[] | null>(null);

  // The files, while open (again when the book's counts change).
  const counts = `${book.done}/${book.working}/${book.failed}`;
  useEffect(() => {
    if (!open) return;
    let current = true;
    api
      .getTranscriptBook(book.id)
      .then((found) => current && setFiles(found.files))
      .catch(() => current && setFiles([]));
    return () => {
      current = false;
    };
  }, [open, book.id, counts]);

  return (
    <>
      <tr>
        <td>
          <button className="link transcripts-table__toggle" type="button" onClick={onToggle} aria-expanded={open}>
            {book.title}
          </button>
          <div className="text-muted">
            {KIND_LABELS[book.kind]} · {book.author}
          </div>
        </td>
        <td className="text-muted">{formatDuration(book.durationMs / 1000)}</td>
        <td>
          {status(book)}
          <div className="meter" aria-hidden="true">
            <div
              className="meter__fill"
              style={{
                width: `${book.files ? (book.done / book.files) * 100 : 0}%`,
              }}
            />
          </div>
        </td>
        <td className="users-table__actions">
          {book.failed > 0 && (
            <button className="button button--ghost" type="button" onClick={onRetry}>
              Retry failed
            </button>
          )}
          {book.done + book.failed > 0 && (
            <button className="button button--ghost button--danger" type="button" onClick={onRemove}>
              Remove text
            </button>
          )}
        </td>
      </tr>
      {open && (
        <tr className="transcripts-table__files">
          <td colSpan={4}>
            {files === null ? (
              <p className="text-muted">Loading…</p>
            ) : (
              <ol>
                {files.map((file) => (
                  <li key={file.id}>
                    <span>{file.title}</span>
                    <span className="text-muted">{formatDuration(file.durationMs / 1000)}</span>
                    <span className={`transcripts-table__status transcripts-table__status--${file.status}`}>
                      {file.status === "working"
                        ? `${Math.round(file.progress * 100)} % · ${file.worker ?? ""}`
                        : file.status === "failed"
                          ? `failed: ${file.error ?? "?"}`
                          : file.status === "done"
                            ? "done"
                            : "waiting"}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
