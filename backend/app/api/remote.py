"""Remote control's WebSocket (services/remote.py): signed in with the web UI's session
cookie, from the web UI's own origin only (browsers send cookies with cross-site
WebSockets too: another site must not drive the user's players)."""

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.deps import SESSION_COOKIE
from app.core.db import Database
from app.services import web_sessions
from app.services.remote import RemoteHub, as_object

router = APIRouter(prefix="/remote", tags=["remote"])

MAX_MESSAGE = 64 * 1024  # a state or a command is far smaller


def _same_origin(websocket: WebSocket) -> bool:
    """Browsers always send Origin: it must be the host the page was served from. Without
    one (not a browser), the session cookie still has to be there."""
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    return urlsplit(origin).netloc.lower() == websocket.headers.get("host", "").lower()


@router.websocket("/ws")
async def remote_socket(websocket: WebSocket) -> None:
    if not _same_origin(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    db: Database = websocket.app.state.db
    token = websocket.cookies.get(SESSION_COOKIE)
    async with db.session() as session:
        found = await web_sessions.resolve(session, token) if token else None
        await session.commit()
    if found is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user = found[1]
    await websocket.accept()

    hub: RemoteHub = websocket.app.state.remote
    lock = asyncio.Lock()  # sends come from this connection and from the others'

    async def send(message: dict[str, Any]) -> None:
        async with lock:
            await websocket.send_json(message)

    member = hub.join(user.id, send)
    try:
        while True:
            text = await websocket.receive_text()
            if len(text) > MAX_MESSAGE:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                break
            try:
                message = as_object(json.loads(text))
            except ValueError:
                continue
            if message is not None:
                await hub.handle(member, message)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.leave(member)
