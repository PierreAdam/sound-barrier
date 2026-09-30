"""Remote control: a web UI tab the user made controllable (a "target") is driven from
another tab, computer or phone signed in to the same account (a "remote").

The server only relays, in memory (nothing is stored): each connection is a WebSocket
(api/remote.py). A target reports its player's state, the hub passes it to the user's
remotes; a remote sends commands, the hub passes them to the target, which applies them
as if its own buttons were clicked. A user only ever sees their own targets.

Only one tab at a time can be the target of a given player (see api/players.py: the
Shared one, or one the user created): another asking is told, and may take over (the
first one is then told it was replaced).

A remote does not only show a target: it mirrors it (the web UI in "remote" mode shows
the target's queue in its own player bar and queue panel, and what the user plays or
queues goes to the target). So a target also sends its queue, when it changes, to the
remotes watching it (a queue can be large: it is not sent to every remote listing targets).

Messages are JSON objects with a "type":
- target -> hub: "target" {player, playerName, device, takeOver}, "state" {state},
  "queue" {queue} (its entries: {revision, keys, tracks}), "stop" (no longer controllable);
- remote -> hub: "remote" (list the targets), "watch" {target} (get that target's queue,
  null: none), "command" {target, command};
- hub -> target: "target-on" {id}, "conflict" {device}, "replaced" {device},
  "command" {command};
- hub -> remote: "targets" {targets}, "state" {target, state}, "queue" {target, queue}
  (watchers only), "error" {message}.

Targets are web UI tabs ("browser"), or server players ("server",
services/server_player.py): members without a WebSocket, whose `send` applies commands.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

log = logging.getLogger(__name__)

# What a remote may ask (the player bar's controls). The target checks the values.
COMMANDS = frozenset(
    {
        "toggle",  # play / pause
        "play",
        "pause",
        "previous",
        "next",
        "seek",  # {position} seconds
        "skip",  # {seconds}, negative: back
        "volume",  # {value} 0..1
        "mute",  # toggle
        "shuffle",  # toggle
        "repeat",  # next mode
        "crossfade",  # toggle
        "pauseAtEnd",  # toggle
        "speed",  # {value}: audiobooks and podcasts
        "crossfadeSeconds",  # {value}
        # The queue. Entries are named by their key (the target's, stable while it is
        # queued: the same song may be queued twice), never by position, which moves.
        "playQueue",  # {tracks, index, startAt?}: replaces the queue
        "add",  # {tracks}: at the end
        "playNext",  # {tracks}: after the current one
        "playAt",  # {key}
        "remove",  # {keys}
        "move",  # {key, before}: before the entry `before` (null: at the end)
        "clear",
        "undo",
    }
)
KINDS = frozenset({"browser", "server"})
MAX_TEXT = 200  # player names, device names

Send = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(eq=False)
class Member:
    """One connection: a target, a remote, or not yet either."""

    user_id: uuid.UUID
    send: Send
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    role: str | None = None  # "target" / "remote"
    player: str | None = None  # target: the player it plays (None: Shared)
    player_name: str = ""
    device: str = ""
    kind: str = "browser"  # of a target: a web UI tab, or a server player
    state: dict[str, Any] | None = None  # target: its last reported state
    queue: dict[str, Any] | None = None  # target: its last reported queue
    watching: str | None = None  # remote: the target whose queue it gets


def as_object(value: object) -> dict[str, Any] | None:
    """A JSON object (a dict), else None."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _text(value: object, default: str = "") -> str:
    return value[:MAX_TEXT] if isinstance(value, str) else default


class RemoteHub:
    def __init__(self) -> None:
        self._members: dict[uuid.UUID, list[Member]] = {}

    def join(self, user_id: uuid.UUID, send: Send, *, kind: str = "browser") -> Member:
        member = Member(user_id, send, kind=kind if kind in KINDS else "browser")
        self._members.setdefault(user_id, []).append(member)
        return member

    async def leave(self, member: Member) -> None:
        members = self._members.get(member.user_id, [])
        if member in members:
            members.remove(member)
        if not members:
            self._members.pop(member.user_id, None)
        if member.role == "target":
            await self._announce(member.user_id)

    async def handle(self, member: Member, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "target":
            await self._target(member, message)
        elif kind == "state" and member.role == "target":
            state = as_object(message.get("state"))
            if state is not None:
                member.state = state
                await self._to_remotes(
                    member.user_id, {"type": "state", "target": member.id, "state": state}
                )
        elif kind == "queue" and member.role == "target":
            queue = as_object(message.get("queue"))
            if queue is not None:
                member.queue = queue
                await self._to_watchers(member, queue)
        elif kind == "stop" and member.role == "target":
            member.role = None
            member.state = None
            member.queue = None
            await self._announce(member.user_id)
        elif kind == "remote":
            member.role = "remote"
            await self._send(member, self._targets_message(member.user_id))
        elif kind == "watch" and member.role == "remote":
            watched = message.get("target")
            member.watching = watched if isinstance(watched, str) else None
            target = self._find(member.user_id, member.watching)
            if target is not None and target.queue is not None:
                await self._send(member, self._queue_message(target, target.queue))
        elif kind == "command" and member.role == "remote":
            await self._command(member, message)

    # --- internals ----------------------------------------------------------------

    def _of(self, user_id: uuid.UUID, role: str) -> list[Member]:
        return [m for m in self._members.get(user_id, []) if m.role == role]

    def _find(self, user_id: uuid.UUID, target_id: object) -> Member | None:
        return next((t for t in self._of(user_id, "target") if t.id == target_id), None)

    async def _target(self, member: Member, message: dict[str, Any]) -> None:
        player = message.get("player")
        player = player if isinstance(player, str) and player else None
        member.player_name = _text(message.get("playerName"), "Shared")
        member.device = _text(message.get("device"), "A browser")
        other = next(
            (
                t
                for t in self._of(member.user_id, "target")
                if t.player == player and t is not member
            ),
            None,
        )
        if other is not None:
            if not message.get("takeOver"):
                # Not controllable meanwhile (e.g. it switched to that player).
                was_target = member.role == "target"
                member.role = None
                member.state = None
                member.queue = None
                await self._send(member, {"type": "conflict", "device": other.device})
                if was_target:
                    await self._announce(member.user_id)
                return
            other.role = None
            other.state = None
            other.queue = None
            await self._send(other, {"type": "replaced", "device": member.device})
        member.role = "target"
        member.player = player
        await self._send(member, {"type": "target-on", "id": member.id})
        await self._announce(member.user_id)

    async def _command(self, member: Member, message: dict[str, Any]) -> None:
        command = as_object(message.get("command"))
        target = self._find(member.user_id, message.get("target"))
        if target is None:
            await self._send(
                member, {"type": "error", "message": "This player can no longer be controlled"}
            )
            return
        if command is None or command.get("name") not in COMMANDS:
            return
        await self._send(target, {"type": "command", "command": command})

    def _targets_message(self, user_id: uuid.UUID) -> dict[str, Any]:
        return {
            "type": "targets",
            "targets": [
                {
                    "id": t.id,
                    "playerName": t.player_name,
                    "device": t.device,
                    "kind": t.kind,
                    "state": t.state,
                }
                for t in self._of(user_id, "target")
            ],
        }

    async def _announce(self, user_id: uuid.UUID) -> None:
        """The user's remotes: the targets changed."""
        await self._to_remotes(user_id, self._targets_message(user_id))

    def _queue_message(self, target: Member, queue: dict[str, Any]) -> dict[str, Any]:
        return {"type": "queue", "target": target.id, "queue": queue}

    async def _to_watchers(self, target: Member, queue: dict[str, Any]) -> None:
        message = self._queue_message(target, queue)
        for remote in self._of(target.user_id, "remote"):
            if remote.watching == target.id:
                await self._send(remote, message)

    async def _to_remotes(self, user_id: uuid.UUID, message: dict[str, Any]) -> None:
        for remote in self._of(user_id, "remote"):
            await self._send(remote, message)

    async def _send(self, member: Member, message: dict[str, Any]) -> None:
        try:
            await member.send(message)
        except Exception:  # a connection closing: it leaves on its own
            log.debug("Remote control: could not send to %s", member.id, exc_info=True)
