"""Utility helpers for broker operations."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, TypeVar, Union, cast

from .errors import IBKRError

log = logging.getLogger(__name__)

T = TypeVar("T")
Func = Callable[..., Union[T, Awaitable[T]]]


async def retry_async(
    func: Func,
    *args: Any,
    retries: int = 3,
    base_delay: float = 0.5,
    action: str = "operation",
) -> T:
    """Execute *func* with exponential backoff retry.

    Parameters
    ----------
    func:
        Callable that may be synchronous or asynchronous.
    retries:
        Total number of attempts before giving up.
    base_delay:
        Initial delay between attempts in seconds; doubles each retry.
    action:
        Descriptive name used in log and error messages.
    """

    for attempt in range(1, retries + 1):
        try:
            result = func(*args)
            if asyncio.iscoroutine(result):
                result = await cast(Awaitable[T], result)
            return cast(T, result)
        except Exception as exc:  # pragma: no cover - network errors
            if attempt == retries:
                log.error("%s failed after %d attempts: %s", action, attempt, exc)
                raise IBKRError(
                    f"{action} failed after {attempt} attempts: {exc}"
                ) from exc
            delay = base_delay * (2 ** (attempt - 1))
            log.warning(
                "%s attempt %d/%d failed: %s; retrying in %.1fs",
                action.capitalize(),
                attempt,
                retries,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    raise IBKRError(f"{action} failed")  # pragma: no cover - defensive
