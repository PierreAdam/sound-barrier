"""Where everything lives: inside the app's folder (like a Pinokio app), nothing elsewhere.

    transcriber/
      config.toml   the server and the worker token (written by `transcriber login`)
      models/       the Whisper models (downloaded on first use)
      work/         the file being transcribed (removed when done)
      env/, .venv/  Python and the libraries (install.ps1)

SB_TRANSCRIBER_HOME moves it all elsewhere.
"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

HOME = Path(os.environ.get("SB_TRANSCRIBER_HOME") or Path(__file__).resolve().parents[2])
CONFIG = HOME / "config.toml"
MODELS = HOME / "models"
WORK = HOME / "work"


class NotConfiguredError(Exception):
    pass


@dataclass
class Config:
    server: str  # e.g. https://music.example.com
    token: str


def load() -> Config:
    try:
        data = tomllib.loads(CONFIG.read_text("utf-8"))
        return Config(server=str(data["server"]).rstrip("/"), token=str(data["token"]))
    except (OSError, tomllib.TOMLDecodeError, KeyError) as error:
        raise NotConfiguredError(
            f"Not signed in to a server ({CONFIG}): run `transcriber login <server url>`"
        ) from error


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(config: Config) -> None:
    CONFIG.write_text(
        "# Written by `transcriber login`. The token only lets this app transcribe podcasts\n"
        "# and audiobooks; revoke it in Sound-Barrier (Settings -> Transcripts).\n"
        f"server = {_quoted(config.server)}\ntoken = {_quoted(config.token)}\n",
        encoding="utf-8",
    )
