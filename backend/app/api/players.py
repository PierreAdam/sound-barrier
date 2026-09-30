"""The web UI's players: each keeps its own queue (api/queue.py, `?player=`). Every browser
plays the Shared queue unless it is assigned to one of these (in its local storage).
A user only ever sees their own."""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ApiModel, CurrentCaller, DbSession
from app.services import web_queue

router = APIRouter(prefix="/players", tags=["players"])


class PlayerOut(ApiModel):
    id: uuid.UUID
    name: str
    song_count: int  # in its queue
    created_at: datetime
    updated_at: datetime  # its queue's last save


class SharedOut(ApiModel):
    song_count: int
    updated_at: datetime | None  # None: never saved


class PlayersOut(ApiModel):
    shared: SharedOut
    players: list[PlayerOut]  # by name, the Shared one not included
    max_players: int


class PlayerIn(ApiModel):
    name: str


def _out(player: web_queue.Player) -> PlayerOut:
    return PlayerOut(**vars(player))


def _refused(error: Exception) -> HTTPException:
    if isinstance(error, web_queue.PlayerNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(error))
    if isinstance(error, web_queue.PlayerNameTakenError):
        return HTTPException(status.HTTP_409_CONFLICT, str(error))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(error))


_ERRORS = (
    web_queue.InvalidPlayerError,
    web_queue.PlayerNameTakenError,
    web_queue.PlayerNotFoundError,
)


@router.get("")
async def list_players(caller: CurrentCaller, session: DbSession) -> PlayersOut:
    players = await web_queue.players(session, caller.user)
    song_count, updated_at = await web_queue.shared(session, caller.user)
    return PlayersOut(
        shared=SharedOut(song_count=song_count, updated_at=updated_at),
        players=[_out(p) for p in players],
        max_players=web_queue.MAX_PLAYERS,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_player(body: PlayerIn, caller: CurrentCaller, session: DbSession) -> PlayerOut:
    try:
        player = await web_queue.create_player(session, caller.user, body.name)
    except _ERRORS as error:
        raise _refused(error) from None
    await session.commit()
    return _out(player)


@router.put("/{player_id}")
async def rename_player(
    player_id: uuid.UUID, body: PlayerIn, caller: CurrentCaller, session: DbSession
) -> PlayerOut:
    try:
        player = await web_queue.rename_player(session, caller.user, player_id, body.name)
    except _ERRORS as error:
        raise _refused(error) from None
    await session.commit()
    return _out(player)


@router.delete("/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_player(player_id: uuid.UUID, caller: CurrentCaller, session: DbSession) -> None:
    try:
        await web_queue.delete_player(session, caller.user, player_id)
    except _ERRORS as error:
        raise _refused(error) from None
    await session.commit()
