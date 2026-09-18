"""Tool dispatch must not block the event loop (watchdog starvation)."""

import asyncio
import threading
import time
from unittest.mock import MagicMock

from spirrow_prismind.server import PrismindServer


def _server_with_slow_sync_catalog(delay: float, log: list) -> PrismindServer:
    server = PrismindServer()
    server._initialized = True

    def slow_sync(project=None):
        log.append(("start", project, threading.current_thread().name))
        time.sleep(delay)
        log.append(("end", project, threading.current_thread().name))
        return MagicMock(success=True, synced_count=1, message="ok")

    catalog = MagicMock()
    catalog.sync_catalog.side_effect = slow_sync
    server._project_tools = MagicMock()
    server._catalog_tools = catalog
    return server


def test_event_loop_keeps_ticking_during_a_long_tool_call():
    log: list = []
    server = _server_with_slow_sync_catalog(0.5, log)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    async def main():
        t = asyncio.create_task(ticker())
        result = await server._dispatch_tool("sync_catalog", {"project": "p"})
        t.cancel()
        return result

    result = asyncio.run(main())

    assert result["success"] is True
    # Blocking the loop for 0.5s would leave the ticker at ~0.
    assert ticks >= 20
    assert log[0][2].startswith("prismind-tool")


def test_concurrent_calls_still_run_one_at_a_time_in_order():
    log: list = []
    server = _server_with_slow_sync_catalog(0.1, log)

    async def main():
        await asyncio.gather(
            server._dispatch_tool("sync_catalog", {"project": "a"}),
            server._dispatch_tool("sync_catalog", {"project": "b"}),
        )

    asyncio.run(main())

    assert [(ev, p) for ev, p, _ in log] == [
        ("start", "a"), ("end", "a"), ("start", "b"), ("end", "b"),
    ]
