import uuid
from typing import Any

from app.services.remote import Member, RemoteHub


class Inbox:
    """What a connection received."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if m["type"] == kind]

    @property
    def last(self) -> dict[str, Any]:
        return self.messages[-1]


def _join(hub: RemoteHub, user: uuid.UUID) -> tuple[Member, Inbox]:
    inbox = Inbox()
    return hub.join(user, inbox), inbox


def _target_message(player: str | None, device: str, take_over: bool = False) -> dict[str, Any]:
    return {
        "type": "target",
        "player": player,
        "playerName": "PC",
        "device": device,
        "takeOver": take_over,
    }


async def test_a_remote_drives_a_target() -> None:
    hub = RemoteHub()
    user = uuid.uuid4()
    pc, pc_inbox = _join(hub, user)
    phone, phone_inbox = _join(hub, user)

    await hub.handle(phone, {"type": "remote"})
    assert phone_inbox.last == {"type": "targets", "targets": []}

    await hub.handle(pc, _target_message(None, "Vivaldi on Windows"))
    assert pc_inbox.last == {"type": "target-on", "id": pc.id}
    announced = phone_inbox.last["targets"]
    assert [(t["id"], t["playerName"], t["device"]) for t in announced] == [
        (pc.id, "PC", "Vivaldi on Windows")
    ]

    state = {"playing": True, "position": 12.5}
    await hub.handle(pc, {"type": "state", "state": state})
    assert phone_inbox.last == {"type": "state", "target": pc.id, "state": state}

    command = {"name": "seek", "position": 42}
    await hub.handle(phone, {"type": "command", "target": pc.id, "command": command})
    assert pc_inbox.last == {"type": "command", "command": command}

    # Only known commands are passed on.
    await hub.handle(phone, {"type": "command", "target": pc.id, "command": {"name": "explode"}})
    assert pc_inbox.last == {"type": "command", "command": command}

    # A remote joining later gets the targets with their last state.
    tablet, tablet_inbox = _join(hub, user)
    await hub.handle(tablet, {"type": "remote"})
    assert tablet_inbox.last["targets"][0]["state"] == state

    await hub.handle(pc, {"type": "stop"})
    assert phone_inbox.last == {"type": "targets", "targets": []}
    await hub.handle(phone, {"type": "command", "target": pc.id, "command": command})
    assert phone_inbox.last["type"] == "error"


async def test_one_target_per_player() -> None:
    hub = RemoteHub()
    user = uuid.uuid4()
    first, first_inbox = _join(hub, user)
    second, second_inbox = _join(hub, user)
    phone, phone_inbox = _join(hub, user)
    await hub.handle(phone, {"type": "remote"})

    await hub.handle(first, _target_message(None, "Edge"))
    await hub.handle(second, _target_message(None, "Vivaldi"))
    assert second_inbox.last == {"type": "conflict", "device": "Edge"}
    assert [t["id"] for t in phone_inbox.last["targets"]] == [first.id]

    # Another player: no conflict.
    other, other_inbox = _join(hub, user)
    await hub.handle(other, _target_message("phone-player", "Firefox"))
    assert len(phone_inbox.last["targets"]) == 2

    # Taking over: the first one is told, and is no longer controllable.
    await hub.handle(second, _target_message(None, "Vivaldi", take_over=True))
    assert first_inbox.last == {"type": "replaced", "device": "Vivaldi"}
    assert {t["id"] for t in phone_inbox.last["targets"]} == {second.id, other.id}

    # A target switching to a player already controlled elsewhere: no longer controllable.
    await hub.handle(other, _target_message(None, "Firefox"))
    assert other_inbox.last == {"type": "conflict", "device": "Vivaldi"}
    assert [t["id"] for t in phone_inbox.last["targets"]] == [second.id]

    # A target leaving (tab closed): the remotes are told.
    await hub.leave(second)
    assert phone_inbox.last["targets"] == []


async def test_users_never_see_each_other() -> None:
    hub = RemoteHub()
    mine, _ = _join(hub, uuid.uuid4())
    await hub.handle(mine, _target_message(None, "Edge"))
    stranger, stranger_inbox = _join(hub, uuid.uuid4())
    await hub.handle(stranger, {"type": "remote"})
    assert stranger_inbox.last == {"type": "targets", "targets": []}
    command = {"name": "pause"}
    await hub.handle(stranger, {"type": "command", "target": mine.id, "command": command})
    assert stranger_inbox.last["type"] == "error"


async def test_only_targets_report_and_only_remotes_command() -> None:
    hub = RemoteHub()
    user = uuid.uuid4()
    target, target_inbox = _join(hub, user)
    await hub.handle(target, _target_message(None, "Edge"))
    remote, remote_inbox = _join(hub, user)
    await hub.handle(remote, {"type": "remote"})
    before = len(remote_inbox.messages)

    # A remote cannot pretend to be a target's state; a target cannot send commands.
    await hub.handle(remote, {"type": "state", "state": {"playing": False}})
    other, other_inbox = _join(hub, user)
    await hub.handle(other, {"type": "command", "target": target.id, "command": {"name": "pause"}})
    assert len(remote_inbox.messages) == before
    assert target_inbox.of("command") == []
    assert other_inbox.messages == []


async def test_watchers_get_the_queue() -> None:
    hub = RemoteHub()
    user = uuid.uuid4()
    pc, _ = _join(hub, user)
    await hub.handle(pc, _target_message(None, "Edge"))
    queue = {"revision": 1, "keys": [0, 1], "tracks": [{"id": "a"}, {"id": "b"}]}
    await hub.handle(pc, {"type": "queue", "queue": queue})

    # Listing the targets does not bring their queues...
    lister, lister_inbox = _join(hub, user)
    await hub.handle(lister, {"type": "remote"})
    # ...watching one does: at once (the last one sent), then at each change.
    phone, phone_inbox = _join(hub, user)
    await hub.handle(phone, {"type": "remote"})
    await hub.handle(phone, {"type": "watch", "target": pc.id})
    assert phone_inbox.last == {"type": "queue", "target": pc.id, "queue": queue}
    changed = {**queue, "revision": 2, "keys": [1]}
    await hub.handle(pc, {"type": "queue", "queue": changed})
    assert phone_inbox.last == {"type": "queue", "target": pc.id, "queue": changed}
    assert lister_inbox.of("queue") == []

    await hub.handle(phone, {"type": "watch", "target": None})
    await hub.handle(pc, {"type": "queue", "queue": queue})
    assert phone_inbox.last["queue"] == changed  # no longer watching

    # Queue commands are passed on, by key.
    command = {"name": "move", "key": 1, "before": 0}
    await hub.handle(phone, {"type": "command", "target": pc.id, "command": command})
    assert _last_command(pc) == command


def _last_command(target: Member) -> dict[str, Any]:
    inbox = target.send
    assert isinstance(inbox, Inbox)
    return inbox.of("command")[-1]["command"]


async def test_server_targets_are_listed_with_their_kind() -> None:
    hub = RemoteHub()
    user = uuid.uuid4()
    commands = Inbox()
    server = hub.join(user, commands, kind="server")
    await hub.handle(server, _target_message("server:1", "Sound-Barrier"))
    phone, phone_inbox = _join(hub, user)
    await hub.handle(phone, {"type": "remote"})
    assert [(t["kind"], t["device"]) for t in phone_inbox.last["targets"]] == [
        ("server", "Sound-Barrier")
    ]
    await hub.handle(phone, {"type": "command", "target": server.id, "command": {"name": "undo"}})
    assert commands.last == {"type": "command", "command": {"name": "undo"}}
