"""Circuit breaker pattern for Redis fallback to HTTP.

Automatically switches from Redis to HTTP forwarding when Redis fails repeatedly.
States: closed (normal), open (fallback), half_open (retry).
"""

import time
from shopee_api.core.logger import setup_logger

logger = setup_logger(__name__)


class RedisCircuitBreaker:
    """Circuit breaker for automatic Redis fallback.

    Opens circuit (falls back to HTTP) after consecutive Redis failures.
    Periodically retries Redis in half-open state.
    """

    def __init__(self, threshold: int = 5, timeout: int = 60):
        """Initialize circuit breaker.

        Args:
            threshold: Number of consecutive failures before opening circuit
            timeout: Seconds to wait before retrying in half-open state
        """
        self.threshold = threshold
        self.timeout = timeout
        self.failure_count = 0
        self.state = "closed"  # closed, open, half_open
        self.opened_at = None

        logger.info(
            f"Circuit breaker initialized: threshold={threshold}, timeout={timeout}s"
        )

    def record_success(self):
        """Record successful Redis operation.

        Resets failure count and closes circuit if it was open.
        """
        if self.state != "closed":
            logger.info(
                f"Circuit breaker: Redis recovered, closing circuit "
                f"(was {self.state}, failures={self.failure_count})"
            )

        self.failure_count = 0
        self.state = "closed"
        self.opened_at = None

    def record_failure(self):
        """Record failed Redis operation.

        Increments failure count and opens circuit if threshold exceeded.
        """
        self.failure_count += 1

        logger.warning(
            f"Circuit breaker: Redis failure recorded "
            f"({self.failure_count}/{self.threshold})"
        )

        if self.failure_count >= self.threshold and self.state == "closed":
            self.state = "open"
            self.opened_at = time.time()
            logger.error(
                f"Circuit breaker: OPEN - Falling back to HTTP forwarding "
                f"after {self.failure_count} consecutive failures"
            )

    def should_attempt_redis(self) -> bool:
        """Check if Redis should be attempted.

        Returns:
            True if Redis should be tried, False to use HTTP fallback
        """
        if self.state == "closed":
            return True

        # Check if timeout has passed, try half-open
        if self.state == "open":
            if time.time() - self.opened_at > self.timeout:
                self.state = "half_open"
                logger.info(
                    f"Circuit breaker: Entering HALF_OPEN state, "
                    f"retrying Redis (timeout={self.timeout}s elapsed)"
                )
                return True
            else:
                # Still open, use HTTP fallback
                return False

        # half_open state - allow retry
        return True

    def get_state(self) -> dict:
        """Get current circuit breaker state.

        Returns:
            Dict with state, failure_count, and opened_at
        """
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "threshold": self.threshold,
            "opened_at": self.opened_at,
            "timeout": self.timeout
        }
