import asyncio
import threading
import time

import pytest

from utils.async_stream import stream_in_thread


def _threads_named(name):
    return [t for t in threading.enumerate() if t.name == name]


async def _collect(agen):
    return [item async for item in agen]


def test_yields_all_items_in_order():
    result = asyncio.run(_collect(stream_in_thread(iter(["a", "b", "c"]), name="koza-test-order")))

    assert result == ["a", "b", "c"]


def test_event_loop_is_not_blocked_while_iterating():
    released = threading.Event()

    def gen():
        # If the bridge iterated on the loop thread, the setter coroutine below
        # could never run and this wait would time out.
        yield released.wait(timeout=5)

    async def main():
        async def release():
            released.set()

        setter = asyncio.create_task(release())
        agen = stream_in_thread(gen(), name="koza-test-loop")
        value = await asyncio.wait_for(agen.__anext__(), timeout=5)
        await setter
        await agen.aclose()
        return value

    assert asyncio.run(main()) is True


def test_exception_propagates_after_items():
    def gen():
        yield 1
        yield 2
        raise RuntimeError("boom")

    async def main():
        received = []
        with pytest.raises(RuntimeError, match="boom"):
            async for item in stream_in_thread(gen(), name="koza-test-error"):
                received.append(item)
        return received

    assert asyncio.run(main()) == [1, 2]


def test_early_close_stops_producer_and_runs_finally():
    produced = [0]
    finalised = threading.Event()
    name = "koza-test-close"
    max_buffer = 4

    def gen():
        try:
            for i in range(100):
                produced[0] += 1
                yield i
        finally:
            finalised.set()

    async def main():
        agen = stream_in_thread(gen(), max_buffer=max_buffer, name=name)
        first = [await agen.__anext__(), await agen.__anext__()]
        await agen.aclose()
        return first

    assert asyncio.run(main()) == [0, 1]
    assert finalised.wait(timeout=5)
    for thread in _threads_named(name):
        thread.join(timeout=5)
        assert not thread.is_alive()
    after_close = produced[0]
    assert after_close <= 2 + max_buffer + 1
    assert produced[0] == after_close


def test_backpressure_bounds_producer_lead():
    produced = [0]
    max_buffer = 2

    def gen():
        for i in range(50):
            produced[0] += 1
            yield i

    async def main():
        consumed = 0
        leads = []
        async for _item in stream_in_thread(gen(), max_buffer=max_buffer, name="koza-test-bp"):
            consumed += 1
            leads.append(produced[0] - consumed)
            await asyncio.sleep(0.01)
        return consumed, leads

    consumed, leads = asyncio.run(main())

    assert consumed == 50
    assert max(leads) <= max_buffer + 1


def test_wrapper_close_reaches_sync_iterator():
    """The endpoint wraps the bridge in another async generator; closing that
    wrapper (what Starlette does on client disconnect) must stop the sync turn."""
    finalised = threading.Event()
    produced = [0]

    def gen():
        try:
            while True:
                produced[0] += 1
                time.sleep(0.01)
                yield {"type": "text", "token": str(produced[0])}
        finally:
            finalised.set()

    async def endpoint_style(events):
        stream = stream_in_thread(events, name="koza-test-wrapper")
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()

    async def main():
        agen = endpoint_style(gen())
        first = await agen.__anext__()
        await agen.aclose()
        return first

    assert asyncio.run(main())["type"] == "text"
    assert finalised.wait(timeout=5)
    before = produced[0]
    time.sleep(0.2)
    assert produced[0] == before


def test_async_iterable_passes_through_without_thread():
    name = "koza-test-passthrough"
    seen_threads = []

    class AsyncSource:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            for item in ("x", "y"):
                seen_threads.append(bool(_threads_named(name)))
                yield item

    result = asyncio.run(_collect(stream_in_thread(AsyncSource(), name=name)))

    assert result == ["x", "y"]
    assert seen_threads == [False, False]


def test_non_iterable_raises_type_error_from_consumer():
    async def main():
        agen = stream_in_thread(42, name="koza-test-noniter")
        with pytest.raises(TypeError, match="int is not iterable") as info:
            await agen.__anext__()
        return info.value

    error = asyncio.run(main())

    assert isinstance(error.__cause__, TypeError)
    assert not _threads_named("koza-test-noniter")


def test_chat_completions_sse_body(monkeypatch):
    from fastapi.testclient import TestClient

    import api_server

    class StubAgent:
        def __init__(self):
            self.messages = []

        def stream_chat(self, _user_input):
            yield {"type": "text", "token": "hi"}
            yield {"type": "tool_done", "elapsed": 0.5}

    monkeypatch.setattr(api_server, "load_config", dict)
    monkeypatch.setattr(api_server, "get_agent", lambda: StubAgent())
    client = TestClient(api_server.app, base_url="http://127.0.0.1:8000")

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    body = response.text
    assert response.status_code == 200
    assert '"delta": {"content": "hi"}, "finish_reason": null' in body
    assert "\\n> \\u2705 *Finished in 0.50s*\\n\\n" in body
    assert '"delta": {}, "finish_reason": "stop"' in body
    assert body.endswith("data: [DONE]\n\n")
