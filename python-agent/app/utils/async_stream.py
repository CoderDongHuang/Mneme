"""Deterministic upstream stream cleanup, including ASGI cancellation scopes."""
from contextlib import asynccontextmanager

import anyio

from app.core.logging import setup_logger

logger = setup_logger("async_stream")


@asynccontextmanager
async def closing_async_iterator(source):
    iterator = source.__aiter__()
    try:
        yield iterator
    finally:
        close = getattr(iterator, "aclose", None)
        if close is not None:
            # Starlette cancels a whole AnyIO scope on disconnect. Shield only
            # resource release, with a bound so a broken provider cannot hang it.
            with anyio.move_on_after(5, shield=True) as scope:
                try:
                    await close()
                except Exception as error:
                    logger.warning("upstream_stream_close_failed error_type=%s", type(error).__name__)
            if scope.cancel_called:
                logger.warning("upstream_stream_close_timeout")
