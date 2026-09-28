"""Registers Subsonic endpoints under `/rest/{name}` and `/rest/{name}.view` (GET and POST).

Each endpoint receives a `SubsonicContext` and returns either a payload for the
`subsonic-response` envelope or a raw `Response` (binary endpoints such as `stream`).
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from app.core.crypto import PasswordCipher
from app.core.db import Database
from app.core.throttle import LoginThrottle, client_address, minutes
from app.models import AppUser
from app.subsonic.auth import authenticate
from app.subsonic.envelope import Payload, ResponseFormat, render, render_error
from app.subsonic.errors import ErrorCode, SubsonicError
from app.subsonic.params import SubsonicParams

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublicContext:
    request: Request
    params: SubsonicParams
    session: AsyncSession


@dataclass(frozen=True)
class SubsonicContext(PublicContext):
    user: AppUser

    @property
    def client(self) -> str:
        return self.params.get("c") or "unknown"


type PublicHandler = Callable[[PublicContext], Awaitable[Payload | Response]]
type Handler = Callable[[SubsonicContext], Awaitable[Payload | Response]]


@dataclass(frozen=True)
class _Endpoint:
    name: str
    handler: Handler | PublicHandler
    public: bool


class SubsonicRegistry:
    def __init__(self) -> None:
        self._endpoints: list[_Endpoint] = []

    def endpoint(self, name: str) -> Callable[[Handler], Handler]:
        """Registers an endpoint that requires an authenticated user."""

        def decorator(handler: Handler) -> Handler:
            self._endpoints.append(_Endpoint(name, handler, public=False))
            return handler

        return decorator

    def public_endpoint(self, name: str) -> Callable[[PublicHandler], PublicHandler]:
        """Registers an endpoint that does not require authentication."""

        def decorator(handler: PublicHandler) -> PublicHandler:
            self._endpoints.append(_Endpoint(name, handler, public=True))
            return handler

        return decorator

    def build_router(self) -> APIRouter:
        router = APIRouter(include_in_schema=False)
        for endpoint in self._endpoints:
            route = _make_route(endpoint)
            for path in (f"/{endpoint.name}", f"/{endpoint.name}.view"):
                router.add_api_route(path, route, methods=["GET", "POST"])
        router.add_api_route("/{method}", _unknown_method, methods=["GET", "POST"])
        return router


registry = SubsonicRegistry()

_CREDENTIAL_ERRORS = (ErrorCode.WRONG_CREDENTIALS, ErrorCode.INVALID_API_KEY)


async def _authenticate(
    request: Request, session: AsyncSession, cipher: PasswordCipher, params: SubsonicParams
) -> AppUser:
    """`authenticate`, with failed attempts throttled per IP address."""
    throttle: LoginThrottle = request.app.state.throttle
    address = client_address(request)
    blocked = throttle.blocked_for(address)
    if blocked:
        raise SubsonicError(
            ErrorCode.WRONG_CREDENTIALS,
            f"Too many failed sign-ins: try again in {minutes(blocked)} minutes",
        )
    try:
        user = await authenticate(session, cipher, params)
    except SubsonicError as error:
        if error.code in _CREDENTIAL_ERRORS:
            throttle.failure(address)
        raise
    throttle.success(address)
    return user


def _make_route(endpoint: _Endpoint) -> Callable[[Request], Awaitable[Response]]:
    async def route(request: Request) -> Response:
        params = await SubsonicParams.from_request(request)
        fmt = ResponseFormat.parse(params.get("f"))
        callback = params.get("callback")
        db: Database = request.app.state.db
        cipher: PasswordCipher = request.app.state.cipher
        try:
            async with db.session() as session:
                if endpoint.public:
                    context: PublicContext = PublicContext(request, params, session)
                else:
                    user = await _authenticate(request, session, cipher, params)
                    context = SubsonicContext(request, params, session, user)
                result = await endpoint.handler(context)  # pyright: ignore[reportArgumentType]
                await session.commit()
        except SubsonicError as error:
            return render_error(error, fmt, callback=callback)
        except Exception:
            logger.exception("Unhandled error in Subsonic endpoint %s", endpoint.name)
            return render_error(
                SubsonicError(ErrorCode.GENERIC, "Internal server error"), fmt, callback=callback
            )
        if isinstance(result, Response):
            return result
        return render(result, fmt, callback=callback)

    route.__name__ = f"subsonic_{endpoint.name}"
    return route


async def _unknown_method(request: Request) -> Response:
    params = await SubsonicParams.from_request(request)
    method = request.path_params["method"].removesuffix(".view")
    logger.info("Unsupported Subsonic method called: %s", method)
    error = SubsonicError(ErrorCode.NOT_FOUND, f"Unknown or unsupported API method: {method}")
    return render_error(
        error, ResponseFormat.parse(params.get("f")), callback=params.get("callback")
    )
