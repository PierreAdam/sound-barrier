from app.core.throttle import LoginThrottle


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_blocks_after_too_many_failures() -> None:
    clock = Clock()
    throttle = LoginThrottle(3, window_seconds=60, block_seconds=300, clock=clock)
    for _ in range(2):
        throttle.failure("1.2.3.4")
    assert throttle.blocked_for("1.2.3.4") == 0
    throttle.failure("1.2.3.4")
    assert throttle.blocked_for("1.2.3.4") == 300
    assert throttle.blocked_for("5.6.7.8") == 0  # per address
    throttle.success("1.2.3.4")  # a right password does not lift the block
    clock.now += 299
    assert throttle.blocked_for("1.2.3.4") == 1
    clock.now += 2
    assert throttle.blocked_for("1.2.3.4") == 0


def test_old_failures_and_successes_reset() -> None:
    clock = Clock()
    throttle = LoginThrottle(3, window_seconds=60, block_seconds=300, clock=clock)
    throttle.failure("a")
    throttle.failure("a")
    clock.now += 61  # outside the window: forgotten
    throttle.failure("a")
    assert throttle.blocked_for("a") == 0
    throttle.failure("a")
    throttle.success("a")  # signing in clears the failures
    throttle.failure("a")
    throttle.failure("a")
    assert throttle.blocked_for("a") == 0
