"""Administration commands: `sound-barrier <command> --help`."""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Callable, Coroutine
from typing import Any

from app.core.config import get_settings
from app.core.crypto import PasswordCipher, generate_secret_key
from app.core.db import Database
from app.scanner.scanner import ScanAlreadyRunningError, run_scan
from app.services import music_folders, users

type Command = Callable[[argparse.Namespace], Coroutine[Any, Any, None]]


def _prompt_password() -> str:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        sys.exit("Passwords do not match")
    if not password:
        sys.exit("Password cannot be empty")
    return password


def _cipher() -> PasswordCipher:
    return PasswordCipher(get_settings().require_secret_key())


def _database() -> Database:
    return Database(get_settings().database_url)


async def cmd_create_user(args: argparse.Namespace) -> None:
    cipher = _cipher()
    password = _prompt_password()
    db = _database()
    try:
        async with db.session() as session:
            user = await users.create_user(
                session, cipher, args.username, password, email=args.email, is_admin=args.admin
            )
            await session.commit()
            print(f"Created user {user.username}{' (admin)' if user.is_admin else ''}")
    except users.UserAlreadyExistsError:
        sys.exit(f"User already exists: {args.username}")
    finally:
        await db.dispose()


async def cmd_set_password(args: argparse.Namespace) -> None:
    cipher = _cipher()
    db = _database()
    try:
        async with db.session() as session:
            user = await users.get_by_username(session, args.username)
            if user is None:
                sys.exit(f"Unknown user: {args.username}")
            await users.set_password(session, user, cipher, _prompt_password())
            await session.commit()
            print(f"Password updated for {user.username}")
    finally:
        await db.dispose()


async def cmd_create_api_key(args: argparse.Namespace) -> None:
    db = _database()
    try:
        async with db.session() as session:
            user = await users.get_by_username(session, args.username)
            if user is None:
                sys.exit(f"Unknown user: {args.username}")
            key = await users.create_api_key(session, user, args.name)
            await session.commit()
            print("API key (shown only once):")
            print(key)
    finally:
        await db.dispose()


async def cmd_add_folder(args: argparse.Namespace) -> None:
    db = _database()
    try:
        async with db.session() as session:
            folder = await music_folders.create(session, args.name, args.path)
            await session.commit()
            print(f"Added music folder {folder.id}: {folder.name} -> {folder.path}")
    except music_folders.InvalidMusicFolderError as error:
        sys.exit(str(error))
    finally:
        await db.dispose()


async def cmd_list_folders(args: argparse.Namespace) -> None:
    db = _database()
    try:
        async with db.session() as session:
            for folder in await music_folders.list_all(session):
                print(f"{folder.id}\t{folder.name}\t{folder.path}")
    finally:
        await db.dispose()


async def cmd_remove_folder(args: argparse.Namespace) -> None:
    db = _database()
    try:
        async with db.session() as session:
            folder = await music_folders.remove(session, args.id)
            if folder is None:
                sys.exit(f"Unknown music folder: {args.id}")
            await session.commit()
            print(f"Removed music folder {folder.id}: {folder.name} (files on disk are untouched)")
    finally:
        await db.dispose()


async def cmd_scan(args: argparse.Namespace) -> None:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = _database()
    try:
        await run_scan(db, full=args.full, workers=get_settings().scan_workers)
    except ScanAlreadyRunningError:
        sys.exit("A scan is already running")
    finally:
        await db.dispose()


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "app.main:create_app", factory=True, host=args.host, port=args.port, reload=args.reload
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="sound-barrier")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("gen-secret", help="print a new SOUND_BARRIER_SECRET_KEY")

    p = sub.add_parser("serve", help="run the HTTP server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=4040)
    p.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")

    p = sub.add_parser("create-user", help="create a user (prompts for the password)")
    p.add_argument("username")
    p.add_argument("--email")
    p.add_argument("--admin", action="store_true")

    p = sub.add_parser("set-password", help="change a user's password")
    p.add_argument("username")

    p = sub.add_parser("create-api-key", help="create an OpenSubsonic API key for a user")
    p.add_argument("username")
    p.add_argument("name", help="label, e.g. the client using it")

    p = sub.add_parser("add-folder", help="add a music folder (library root)")
    p.add_argument("name")
    p.add_argument("path")

    sub.add_parser("list-folders", help="list music folders")

    p = sub.add_parser(
        "remove-folder",
        help="unregister a music folder and forget its songs (files are not touched)",
    )
    p.add_argument("id", type=int, help="folder id, see list-folders")

    p = sub.add_parser("scan", help="scan the library now")
    p.add_argument("--full", action="store_true", help="re-read every file, not only changes")

    args = parser.parse_args()
    if args.command == "gen-secret":
        print(generate_secret_key())
        return
    if args.command == "serve":
        _serve(args)
        return

    commands: dict[str, Command] = {
        "create-user": cmd_create_user,
        "set-password": cmd_set_password,
        "create-api-key": cmd_create_api_key,
        "add-folder": cmd_add_folder,
        "list-folders": cmd_list_folders,
        "remove-folder": cmd_remove_folder,
        "scan": cmd_scan,
    }
    asyncio.run(commands[args.command](args))


if __name__ == "__main__":
    main()
