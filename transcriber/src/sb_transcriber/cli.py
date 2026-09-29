"""transcriber: gives Sound-Barrier's podcasts and audiobooks their text, on this PC's GPU.

    transcriber login https://music.example.com     (asks for the worker token)
    transcriber list                                books / shows that wait for text
    transcriber show "dune"                         the files of one, and their state
    transcriber run "dune" --gpu 0                  transcribes it (and more: several names)
    transcriber run --all --gpu all                 everything that waits, on every GPU
    transcriber devices                             the GPUs CTranslate2 sees

--gpu: a GPU (0), a list (0,1) or all: one worker per GPU; they never take the same file.
"""

import argparse
import contextlib
import getpass
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

from sb_transcriber import config, gpus
from sb_transcriber.client import Claim, Client, LostClaimError, ServerError

RENEW_EVERY = 60.0  # seconds; the server's lease is longer (10 minutes)
MAX_FAILURES = 3  # in a row: something is wrong with this PC (e.g. CUDA), stop
CHILD_STATUS_EVERY = 5.0  # a GPU worker (--gpu all) prints its progress this often

_child = False  # a worker of `--gpu all`: full lines, the parent prefixes them
_last_status = 0.0


def _duration(ms: int) -> str:
    if ms < 60_000:
        return f"{round(ms / 1000)} s"
    minutes = round(ms / 60_000)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d}"


def _client() -> Client:
    return Client(config.load())


# --- login, devices ------------------------------------------------------------


def cmd_login(args: argparse.Namespace) -> None:
    server = args.server.rstrip("/")
    if not server.startswith(("http://", "https://")):
        server = f"https://{server}"
    token = args.token or getpass.getpass(
        "Worker token (Sound-Barrier, Settings -> Transcripts; the input is hidden): "
    )
    found = config.Config(server=server, token=token.strip())
    client = Client(found)
    try:
        hello = client.hello()
    finally:
        client.close()
    config.save(found)
    print(f'Signed in to {hello["server"]} {hello["version"]} at {server} as "{hello["worker"]}".')
    print(f"Saved in {config.CONFIG}.")


def cmd_devices(args: argparse.Namespace) -> None:
    del args
    from sb_transcriber.cuda import device_count

    print(f"CUDA devices seen by CTranslate2: {device_count()}")
    if shutil.which("nvidia-smi"):
        subprocess.run(["nvidia-smi", "-L"], check=False)


# --- list, show ------------------------------------------------------------------


def _resolve(client: Client, names: list[str], kind: str | None) -> list[dict[str, Any]]:
    """Books by id or by (part of) their title."""
    books = client.books(kind)
    found: list[dict[str, Any]] = []
    for name in names:
        exact = [b for b in books if b["id"] == name]
        matches = exact or [b for b in books if name.casefold() in b["title"].casefold()]
        if not matches:
            raise SystemExit(f'No podcast or audiobook matches "{name}" (see `transcriber list`)')
        if len(matches) > 1:
            listed = "\n".join(f"  {b['id']}  {b['title']} ({b['author']})" for b in matches)
            raise SystemExit(
                f'"{name}" matches several, use more of the title or the id:\n{listed}'
            )
        found.append(matches[0])
    return found


def cmd_list(args: argparse.Namespace) -> None:
    client = _client()
    try:
        books = client.books(args.kind)
    finally:
        client.close()
    shown = books if args.all else [b for b in books if b["pending"] or b["working"] or b["failed"]]
    if not shown:
        print("Nothing waits for text." if books else "No podcasts or audiobooks on the server.")
        return
    for book in shown:
        state = f"{book['done']}/{book['files']} done"
        if book["working"]:
            state += f", {book['working']} in progress"
        if book["failed"]:
            state += f", {book['failed']} failed"
        kind = "podcast  " if book["kind"] == "podcasts" else "audiobook"
        print(
            f"{kind}  {book['title']} ({book['author']})  ·  "
            f"{_duration(book['durationMs'])}  ·  {state}"
        )
    waiting = sum(b["pending"] for b in books)
    print(f"\n{waiting} file(s) wait for text.")


def cmd_show(args: argparse.Namespace) -> None:
    client = _client()
    try:
        (book,) = _resolve(client, [args.book], None)
        found = client.book(book["id"])
    finally:
        client.close()
    print(f"{book['title']} ({book['author']})  ·  id {book['id']}")
    for file in found["files"]:
        state = file["status"]
        if state == "working":
            state = f"working, {round(file['progress'] * 100)} % ({file['worker']})"
        elif state == "failed":
            state = f"failed: {file['error']}"
        print(f"  {file['fileName']}  ·  {_duration(file['durationMs'])}  ·  {state}")


# --- run -----------------------------------------------------------------------------


class _Renewer:
    """Keeps the claim alive (and shows the progress on the server) at most once a minute."""

    def __init__(self, client: Client, song_id: str) -> None:
        self._client = client
        self._song_id = song_id
        self._last = time.monotonic()

    def __call__(self, progress: float | None, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last >= RENEW_EVERY:
            self._client.progress(self._song_id, progress)
            self._last = now


def _status(text: str, final: bool = False) -> None:
    """The current step, rewritten in place (a GPU worker: a line now and then)."""
    global _last_status
    if _child:
        now = time.monotonic()
        if final or now - _last_status >= CHILD_STATUS_EVERY:
            print(text.strip(), flush=True)
            _last_status = now
        return
    width = shutil.get_terminal_size((100, 20)).columns - 1
    print(f"\r{text[:width]:<{width}}", end="", flush=True)
    if final:
        print()


def _process(client: Client, engine: Any, claim: Claim, language: str | None) -> None:
    """Downloads, transcribes and sends one file (the claim is renewed all along)."""
    work = config.WORK / f"{claim.song_id}.{claim.suffix}"
    renew = _Renewer(client, claim.song_id)
    label = f"{claim.book} · {claim.title}"
    seconds = claim.duration_ms / 1000
    try:

        def downloaded(received: int) -> None:
            renew(0.0)
            _status(f"  {label}: downloading {received * 100 // max(claim.size, 1)} %")

        client.download(claim, work, downloaded)
        started = time.monotonic()

        def transcribed(progress: float) -> None:
            renew(progress)
            elapsed = time.monotonic() - started
            speed = f" · {progress * seconds / elapsed:.0f}x real time" if elapsed > 5 else ""
            _status(f"  {label}: {progress * 100:.0f} %{speed}")

        _status(f"  {label}: transcribing…")
        result = engine.transcribe(work, seconds, language, transcribed)
        renew(0.99, force=True)
        answer = client.upload(claim.song_id, engine.name, result.language, result.lines)
        elapsed = time.monotonic() - started
        where = "database and .lrc file" if answer.get("lrcWritten") else "database"
        _status(
            f"  {label}: done, {len(result.lines)} lines ({result.language or '?'}), "
            f"{elapsed / 60:.1f} min ({seconds / max(elapsed, 1):.0f}x real time), in the {where}",
            final=True,
        )
    finally:
        work.unlink(missing_ok=True)


def _work_through(
    client: Client,
    engine: Any,
    claim_next: Callable[[], Claim | None],
    language: str | None,
) -> int:
    """Claims and processes files until there are none; returns how many were done."""
    done = failures = 0
    while True:
        claim = claim_next()
        if claim is None:
            return done
        try:
            _process(client, engine, claim, language)
            done += 1
            failures = 0
        except KeyboardInterrupt:
            print("\nStopped: the file goes back to the queue.")
            with contextlib.suppress(ServerError):  # else the claim runs out by itself
                client.release(claim.song_id)
            raise
        except LostClaimError as error:
            print(f"\n  Skipped: {error}")
        except ServerError:
            raise
        except Exception as error:  # the audio or the GPU: the file is marked as failed
            failures += 1
            print(f"\n  Failed: {type(error).__name__}: {error}")
            client.fail(claim.song_id, f"{type(error).__name__}: {error}")
            if failures >= MAX_FAILURES:
                raise SystemExit(
                    f"{MAX_FAILURES} failures in a row: stopping (see the errors above)"
                ) from error


def _gpu(args: argparse.Namespace) -> int | None:
    """The GPU of this process; None: several were asked for, and their workers were run."""
    global _child
    chosen = gpus.parse(args.gpu)
    if len(chosen) > 1 and not args.child:
        code = gpus.run_workers(sys.argv[1:], chosen)
        if code:
            sys.exit(code)
        return None
    _child = args.child
    gpus.use(chosen[0])
    return chosen[0]


def cmd_run(args: argparse.Namespace) -> None:
    if not args.books and not args.all:
        raise SystemExit("Name books / shows to transcribe (see `transcriber list`), or --all")
    gpu = _gpu(args)
    if gpu is None:
        return
    client = _client()
    try:
        client.hello()
        books = _resolve(client, args.books, args.kind) if args.books else []
        print(
            f"Loading whisper {args.model} on GPU {gpu} ({args.compute_type}); "
            f"the first time it is downloaded into {config.MODELS}…"
        )
        from sb_transcriber.engine import Engine

        engine = Engine(args.model, 0, args.compute_type, args.batch_size)  # its only GPU
        instance = f"GPU {gpu}"
        targets: list[str | None] = [b["id"] for b in books] or [None]
        total = 0
        for album_id in targets:
            if album_id is not None:
                book = next(b for b in books if b["id"] == album_id)
                print(f"{book['title']} ({book['author']})")

            def claim_next(album_id: str | None = album_id) -> Claim | None:
                return client.claim(
                    album_id=album_id,
                    kind=args.kind,
                    retry_failed=args.retry_failed,
                    instance=instance,
                )

            total += _work_through(client, engine, claim_next, args.language)
        print(f"Finished: {total} file(s) transcribed." if total else "Nothing left to do.")
    finally:
        client.close()


# --- main ------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transcriber",
        description="Speech to text for Sound-Barrier's podcasts and audiobooks, on this PC's GPU.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    login = commands.add_parser("login", help="sign in to a server with a worker token")
    login.add_argument("server", help="the server's address, e.g. https://music.example.com")
    login.add_argument("--token", help="the worker token (asked for if not given)")
    login.set_defaults(func=cmd_login)

    devices = commands.add_parser("devices", help="the GPUs that can be used")
    devices.set_defaults(func=cmd_devices)

    kinds = ("audiobooks", "podcasts")
    listing = commands.add_parser("list", help="what waits for text")
    listing.add_argument("--kind", choices=kinds)
    listing.add_argument("--all", action="store_true", help="also what is finished")
    listing.set_defaults(func=cmd_list)

    show = commands.add_parser("show", help="the files of a book / show")
    show.add_argument("book", help="its id, or (part of) its title")
    show.set_defaults(func=cmd_show)

    run = commands.add_parser("run", help="transcribe")
    run.add_argument("books", nargs="*", help="ids or (parts of) titles")
    run.add_argument("--all", action="store_true", help="everything that waits")
    run.add_argument("--kind", choices=kinds, help="only audiobooks, or only podcasts")
    run.add_argument(
        "--gpu", default="0", help="a GPU (see `devices`), a list (0,1) or all; default 0"
    )
    run.add_argument(gpus.CHILD_FLAG, dest="child", action="store_true", help=argparse.SUPPRESS)
    run.add_argument(
        "--model",
        default="large-v3",
        help="large-v3 (default, best), large-v3-turbo (faster, nearly as good), medium, small",
    )
    run.add_argument("--language", help="e.g. fr, en (default: detected per file)")
    run.add_argument(
        "--compute-type", default="float16", help="float16 (default), int8_float16 (less memory)"
    )
    run.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="segments decoded together (default 8; lower it if the GPU runs out of memory, "
        "1: one by one, slower)",
    )
    run.add_argument("--retry-failed", action="store_true", help="take failed files again")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        args.func(args)
    except (config.NotConfiguredError, ServerError) as error:
        print(f"\n{error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
