"""
Shared utility helpers used across the pipeline.

  - load_json / save_json  — safe file I/O with atomic-ish writes
  - retry_on_transient     — decorator for exponential-backoff retries on
                             HTTP 429 / 5xx responses from requests.Response
"""

import json
import os
import time
import functools
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON state helpers
# ---------------------------------------------------------------------------

def load_json(path: str, default: Any) -> Any:
    """Return parsed JSON from *path*, or *default* if the file doesn't exist."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def save_json(path: str, data: Any) -> None:
    """Atomically write *data* as pretty-printed JSON to *path*.

    Writes to a temp file first, then renames so a crash mid-write never
    leaves a truncated file behind.
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)  # atomic on POSIX; best-effort on Windows


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def retry_on_transient(
    max_attempts: int = 4,
    base_delay: float = 2.0,
    backoff: float = 2.0,
):
    """Decorator: retry the wrapped function on transient HTTP / network errors.

    The wrapped function must raise ``requests.HTTPError`` (from
    ``response.raise_for_status()``) or ``requests.ConnectionError`` /
    ``requests.Timeout`` for the retry logic to kick in.

    Args:
        max_attempts: total attempts (including the first).
        base_delay: seconds to wait before the second attempt.
        backoff: multiplier applied to the delay after each failure.

    Raises:
        The last exception if all attempts are exhausted.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except requests.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else None
                    if status not in _RETRYABLE_STATUS:
                        raise  # non-retryable (4xx client errors, etc.)
                    last_exc = exc
                    logger.warning(
                        "%s: HTTP %s on attempt %d/%d — retrying in %.1fs",
                        func.__name__, status, attempt, max_attempts, delay,
                    )
                except (requests.ConnectionError, requests.Timeout) as exc:
                    last_exc = exc
                    logger.warning(
                        "%s: network error on attempt %d/%d — retrying in %.1fs: %s",
                        func.__name__, attempt, max_attempts, delay, exc,
                    )

                if attempt < max_attempts:
                    time.sleep(delay)
                    delay *= backoff

            raise last_exc  # type: ignore[misc]

        return wrapper
    return decorator
