"""
Route-level rate limiting for Flask endpoints.

Prevents API abuse and accidental rapid-fire requests from
overwhelming eBay's Trading API. Uses a sliding window approach
with per-route tracking.

Configurable per-route limits allow different thresholds for
read operations (higher limit) vs. write operations (lower limit).
"""

import time
import logging
from functools import wraps
from collections import defaultdict

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Sliding-window rate limiter for Flask routes.

    Tracks request timestamps per route and rejects requests
    that exceed the configured rate. Thread-safe via GIL for
    typical Flask deployments.
    """

    def __init__(self, default_limit: int = 30, window_seconds: int = 60):
        """
        Args:
            default_limit: Max requests per window (default).
            window_seconds: Time window in seconds.
        """
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self._requests = defaultdict(list)

    def _cleanup(self, key: str) -> None:
        """Remove expired timestamps from the sliding window."""
        cutoff = time.time() - self.window_seconds
        self._requests[key] = [
            t for t in self._requests[key] if t > cutoff
        ]

    def is_allowed(self, key: str, limit: int = None) -> bool:
        """
        Check if a request is allowed under the rate limit.

        Args:
            key: Rate limit key (typically route name or IP+route).
            limit: Override limit for this check.

        Returns:
            True if the request is allowed, False if rate limited.
        """
        limit = limit or self.default_limit
        self._cleanup(key)

        if len(self._requests[key]) >= limit:
            logger.warning(
                f"Rate limit exceeded for {key}: "
                f"{len(self._requests[key])}/{limit} in {self.window_seconds}s"
            )
            return False

        self._requests[key].append(time.time())
        return True

    def get_remaining(self, key: str, limit: int = None) -> int:
        """
        Get the number of requests remaining in the current window.

        Args:
            key: Rate limit key.
            limit: Override limit for this check.

        Returns:
            Number of requests remaining.
        """
        limit = limit or self.default_limit
        self._cleanup(key)
        return max(0, limit - len(self._requests[key]))

    def reset(self, key: str = None) -> None:
        """
        Reset rate limit counters.

        Args:
            key: Specific key to reset, or None to reset all.
        """
        if key:
            self._requests.pop(key, None)
        else:
            self._requests.clear()


# Global rate limiter instance
_limiter = RateLimiter()


def rate_limit(limit: int = 30, window: int = 60, key_func=None):
    """
    Flask route decorator for rate limiting.

    Usage:
        @app.route('/api/revise')
        @rate_limit(limit=10, window=60)
        def revise_item():
            ...

    Args:
        limit: Maximum requests allowed per window.
        window: Window duration in seconds.
        key_func: Optional function to extract rate limit key from request.
                  Defaults to using the endpoint name.

    Returns:
        Decorator function.
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            # Import here to avoid circular imports
            from flask import request, jsonify

            if key_func:
                key = key_func(request)
            else:
                key = f"{request.remote_addr}:{request.endpoint}"

            if not _limiter.is_allowed(key, limit):
                remaining = _limiter.get_remaining(key, limit)
                return jsonify({
                    "error": "Rate limit exceeded",
                    "retry_after": window,
                    "remaining": remaining,
                }), 429

            return f(*args, **kwargs)
        return wrapped
    return decorator
