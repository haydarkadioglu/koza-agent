"""
Bridge a blocking iterator into an async iterator without blocking the loop.

``Agent.stream_chat`` is a synchronous generator: each ``next()`` may block for
seconds or minutes (LLM latency, shell commands, file reads). Iterating it
directly inside an ``async def`` freezes the whole event loop for the turn, so
every other request to the API server stalls and SSE chunks are not flushed.

``stream_in_thread`` pulls items on a daemon worker thread and hands them to
the event loop through a bounded queue, so the loop stays responsive and the
producer never runs more than ``max_buffer`` items ahead of the consumer.
Closing the async iterator early closes the sync iterator from its own thread,
so its ``finally:`` blocks run and the underlying work stops.

Pure stdlib — no dependency on core or any provider.
"""
import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_BUFFER = 128
_OFFER_POLL_SECONDS = 0.005
_RESULT_POLL_SECONDS = 0.1

_ITEM = "item"
_ERROR = "error"
_END = "end"


async def stream_in_thread(
    iterable: Any,
    *,
    max_buffer: int = DEFAULT_MAX_BUFFER,
    name: str = "koza-stream",
) -> AsyncIterator[Any]:
    """Async-iterate a blocking iterator without blocking the event loop."""
    if hasattr(iterable, "__aiter__"):
        async for item in iterable:
            yield item
        return

    try:
        iterator = iter(iterable)
    except TypeError as exc:
        raise TypeError(f"{type(iterable).__name__} is not iterable") from exc

    if max_buffer < 1:
        raise ValueError("max_buffer must be at least 1")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=max_buffer)
    closed = threading.Event()
    pending: list[concurrent.futures.Future | None] = [None]

    async def _offer(entry: tuple[str, Any]) -> None:
        while not closed.is_set():
            try:
                queue.put_nowait(entry)
                return
            except asyncio.QueueFull:
                await asyncio.sleep(_OFFER_POLL_SECONDS)

    def _deliver(kind: str, payload: Any) -> bool:
        """Hand one entry to the loop; False means stop producing."""
        if closed.is_set():
            return False
        try:
            fut = asyncio.run_coroutine_threadsafe(_offer((kind, payload)), loop)
        except RuntimeError:
            return False  # loop already closed
        pending[0] = fut
        try:
            while True:
                try:
                    fut.result(timeout=_RESULT_POLL_SECONDS)
                    break
                except concurrent.futures.TimeoutError:
                    # Guard against a loop that stopped without running the offer.
                    if closed.is_set() or loop.is_closed():
                        fut.cancel()
                        return False
        except (concurrent.futures.CancelledError, RuntimeError):
            return False  # loop gone / bridge closed: stop quietly
        finally:
            pending[0] = None
        return not closed.is_set()

    def _produce() -> None:
        exhausted = False
        try:
            while not closed.is_set():
                try:
                    item = next(iterator)
                except StopIteration:
                    exhausted = True
                    _deliver(_END, None)
                    return
                except BaseException as exc:  # noqa: BLE001 - forwarded; consumer must not hang
                    exhausted = True
                    _deliver(_ERROR, exc)
                    return
                if not _deliver(_ITEM, item):
                    return
        finally:
            if not exhausted:
                close = getattr(iterator, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        logger.debug("Error while closing %s iterator", name, exc_info=True)

    threading.Thread(target=_produce, name=name, daemon=True).start()

    try:
        while True:
            kind, payload = await queue.get()
            if kind == _ITEM:
                yield payload
            elif kind == _ERROR:
                raise payload
            else:
                return
    finally:
        # Runs on break / aclose() / client disconnect (GeneratorExit or
        # CancelledError) as well as on normal end; the exception re-raises.
        closed.set()
        fut = pending[0]
        if fut is not None:
            fut.cancel()
        while not queue.empty():
            queue.get_nowait()
