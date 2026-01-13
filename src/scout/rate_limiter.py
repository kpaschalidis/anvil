import logging
import time

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, requests_per_minute: int = 30, min_delay: float = 0.5):
        self.requests_per_minute = requests_per_minute
        self.min_delay = min_delay
        self.last_request_time: float = 0.0
        self.request_count: int = 0
        self.window_start: float = time.time()

    def wait(self) -> None:
        now = time.time()

        if now - self.window_start >= 60:
            self.window_start = now
            self.request_count = 0

        if self.request_count >= self.requests_per_minute:
            sleep_time = 60 - (now - self.window_start)
            if sleep_time > 0:
                logger.debug(f"Rate limit reached, sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)
            self.window_start = time.time()
            self.request_count = 0

        elapsed = now - self.last_request_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)

        self.last_request_time = time.time()
        self.request_count += 1
