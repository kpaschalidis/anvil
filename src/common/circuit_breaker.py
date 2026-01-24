import time


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout_s: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self._failures = 0
        self._opened_at: float | None = None

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold and self._opened_at is None:
            self._opened_at = time.monotonic()

    def can_execute(self) -> bool:
        if self._opened_at is None:
            return True
        if (time.monotonic() - self._opened_at) >= self.recovery_timeout_s:
            self._opened_at = None
            self._failures = 0
            return True
        return False

    def state(self) -> str:
        return "open" if self._opened_at is not None else "closed"

