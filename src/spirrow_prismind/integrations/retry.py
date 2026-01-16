"""Retry utilities with exponential backoff for Spirrow-Prismind."""

import logging
import random
import time
from functools import wraps
from typing import Callable, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default retryable exceptions for HTTP operations
RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.ConnectError,
)


def with_retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    retryable_exceptions: tuple = RETRYABLE_EXCEPTIONS,
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for retry with exponential backoff and jitter.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay in seconds (default: 0.5)
        max_delay: Maximum delay in seconds (default: 10.0)
        retryable_exceptions: Tuple of exceptions to retry on
        on_retry: Optional callback called on each retry (exception, attempt)

    Returns:
        Decorated function with retry logic

    Example:
        @with_retry(max_retries=3)
        def fetch_data():
            return httpx.get("https://api.example.com/data")
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        # Calculate delay with exponential backoff
                        delay = min(base_delay * (2**attempt), max_delay)
                        # Add jitter (up to 10% of delay)
                        jitter = random.uniform(0, delay * 0.1)
                        delay += jitter

                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}. "
                            f"Waiting {delay:.2f}s..."
                        )

                        if on_retry:
                            on_retry(e, attempt + 1)

                        time.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_retries} retries exhausted for {func.__name__}: {e}"
                        )

            # If we get here, all retries failed
            if last_exception:
                raise last_exception
            # This should never happen, but satisfy type checker
            raise RuntimeError("Unexpected retry state")

        return wrapper

    return decorator


def retry_on_network_error(func: Callable[..., T]) -> Callable[..., T]:
    """Convenience decorator for retrying on network errors.

    Uses default settings: 3 retries, 0.5s base delay, 10s max delay.

    Example:
        @retry_on_network_error
        def call_api():
            return httpx.get("https://api.example.com")
    """
    return with_retry()(func)


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 10.0,
        enabled: bool = True,
    ):
        """Initialize retry configuration.

        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            enabled: Whether retry is enabled
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.enabled = enabled

    def create_decorator(
        self,
        retryable_exceptions: tuple = RETRYABLE_EXCEPTIONS,
        on_retry: Callable[[Exception, int], None] | None = None,
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Create a retry decorator with this configuration.

        Args:
            retryable_exceptions: Tuple of exceptions to retry on
            on_retry: Optional callback called on each retry

        Returns:
            Retry decorator
        """
        if not self.enabled:
            # Return identity decorator if retry is disabled
            def identity(func: Callable[..., T]) -> Callable[..., T]:
                return func

            return identity

        return with_retry(
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            retryable_exceptions=retryable_exceptions,
            on_retry=on_retry,
        )


# Global default retry config
default_retry_config = RetryConfig()
