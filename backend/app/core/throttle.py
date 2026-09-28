"""Throttling of failed sign-ins, per IP address (web sign-in and Subsonic API).

After `max_failures` failures within `window`, the address is refused for `block`, even
with the right password (a guess that happens to be right must not get through either).
A successful sign-in clears the address's failures. Kept in memory: one process.
"""

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from starlette.requests import Request

logger = logging.getLogger(__name__)


@dataclass
class _Address:
    failures: deque[float] = field(default_factory=deque[float])
    blocked_until: float = 0.0


class LoginThrottle:
    def __init__(
        self,
        max_failures: int = 10,
        window_seconds: float = 15 * 60,
        block_seconds: float = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self.block = block_seconds
        self._now = clock
        self._addresses: dict[str, _Address] = {}

    def blocked_for(self, address: str) -> float:
        """Seconds this address is still refused (0: allowed)."""
        state = self._addresses.get(address)
        if state is None:
            return 0.0
        return max(0.0, state.blocked_until - self._now())

    def failure(self, address: str) -> None:
        now = self._now()
        state = self._addresses.setdefault(address, _Address())
        while state.failures and now - state.failures[0] > self.window:
            state.failures.popleft()
        state.failures.append(now)
        if len(state.failures) >= self.max_failures and state.blocked_until <= now:
            state.blocked_until = now + self.block
            state.failures.clear()
            logger.warning(
                "Sign-ins from %s refused for %d minutes: %d failures",
                address,
                self.block // 60,
                self.max_failures,
            )
        self._forget_old(now)

    def success(self, address: str) -> None:
        state = self._addresses.get(address)
        if state is not None and state.blocked_until <= self._now():
            del self._addresses[address]

    def _forget_old(self, now: float) -> None:
        """Keeps the table small: addresses with nothing recent go."""
        if len(self._addresses) < 1000:
            return
        for address in [
            a
            for a, s in self._addresses.items()
            if s.blocked_until <= now and (not s.failures or now - s.failures[-1] > self.window)
        ]:
            del self._addresses[address]


def minutes(seconds: float) -> int:
    return max(1, round(seconds / 60))


def client_address(request: Request) -> str:
    """The caller's IP address (the real one behind the reverse proxy: uvicorn applies
    X-Forwarded-For from the trusted proxies, FORWARDED_ALLOW_IPS)."""
    return request.client.host if request.client else "unknown"
