"""Tool dispatch must not block the event loop (watchdog starvation)."""

import asyncio
import threading
import time
from unittest.mock import MagicMock

import pytest

from spirrow_prismind.integrations import FilesystemDocumentStore
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


# --- the filesystem rebuild runs beside the tool worker ---------------------


def _server_with_filesystem_rebuild(delay: float, log: list) -> PrismindServer:
    server = _server_with_slow_sync_catalog(delay, log)
    server._document_store = MagicMock(spec=FilesystemDocumentStore)

    def identity(identity_name, user=None):
        log.append(("identity", identity_name, threading.current_thread().name))
        return MagicMock(success=True, found=True, identity=None, message="")

    def search(**kwargs):
        log.append(("search", kwargs["project"], threading.current_thread().name))
        return MagicMock(success=True, total_count=0, documents=[], message="")

    server._session_tools = MagicMock()
    server._session_tools.get_identity.side_effect = identity
    server._catalog_tools.search_catalog.side_effect = search
    return server


def _events(log: list) -> list:
    return [(ev, arg) for ev, arg, _ in log]


async def _after_rebuild_started(log: list, coro):
    while not log:
        await asyncio.sleep(0.005)
    return await coro


def test_identity_lookup_does_not_wait_for_a_rebuild():
    log: list = []
    server = _server_with_filesystem_rebuild(0.3, log)

    async def main():
        await asyncio.gather(
            server._dispatch_tool("sync_catalog", {"project": "p"}),
            _after_rebuild_started(
                log, server._dispatch_tool("get_identity", {"identity_name": "Bohr"})
            ),
        )

    asyncio.run(main())

    assert _events(log) == [("start", "p"), ("identity", "Bohr"), ("end", "p")]
    threads = {ev: thread for ev, _, thread in log}
    assert threads["start"].startswith("prismind-catalog")
    assert threads["identity"].startswith("prismind-tool")


def test_catalog_tools_wait_for_a_rebuild_without_holding_the_tool_worker():
    log: list = []
    server = _server_with_filesystem_rebuild(0.3, log)

    async def search_then_identity():
        # search_catalog is queued first; get_identity must still overtake it.
        search = asyncio.create_task(
            server._dispatch_tool("search_catalog", {"project": "p"})
        )
        await asyncio.sleep(0.05)
        await server._dispatch_tool("get_identity", {"identity_name": "Bohr"})
        await search

    async def main():
        await asyncio.gather(
            server._dispatch_tool("sync_catalog", {"project": "p"}),
            _after_rebuild_started(log, search_then_identity()),
        )

    asyncio.run(main())

    assert _events(log) == [
        ("start", "p"), ("identity", "Bohr"), ("end", "p"), ("search", "p"),
    ]


def test_a_cancelled_rebuild_call_still_holds_the_catalog_until_it_ends():
    log: list = []
    server = _server_with_filesystem_rebuild(0.3, log)

    async def main():
        rebuild = asyncio.create_task(
            server._dispatch_tool("sync_catalog", {"project": "p"})
        )
        while not log:
            await asyncio.sleep(0.005)
        rebuild.cancel()  # the MCP caller gave up; the worker keeps going
        await server._dispatch_tool("search_catalog", {"project": "p"})

    asyncio.run(main())

    assert _events(log) == [("start", "p"), ("end", "p"), ("search", "p")]


@pytest.mark.parametrize(
    "filesystem, args",
    [
        (True, {}),  # current project comes from the memory client
        (False, {"project": "p"}),  # the Google backend reads Sheets and Docs
    ],
)
def test_rebuilds_that_share_clients_stay_on_the_tool_worker(filesystem, args):
    log: list = []
    server = _server_with_slow_sync_catalog(0.01, log)
    if filesystem:
        server._document_store = MagicMock(spec=FilesystemDocumentStore)

    asyncio.run(server._dispatch_tool("sync_catalog", args))

    assert log[0][2].startswith("prismind-tool")
