"""HTTP (SSE) transport and liveness plumbing for the Prismind MCP server.

The server historically spoke stdio only and was put on the network by
wrapping it in ``npx mcp-proxy``. mcp-proxy (6.7.16, the latest release at
the time of writing) connects *one* stdio child at startup and multiplexes
every HTTP session onto it, and it never supervises that child. So when the
child exits -- e.g. the ``anyio.BrokenResourceError`` that races out of
``mcp.server.stdio`` when a client disconnects mid-session -- the node
process stays up, keeps answering ``GET /sse`` with 200, and every
subsequent ``tools/list`` fails with ``Not connected``. systemd sees an
active unit (the corpse is a grandchild), so ``Restart=always`` never fires,
and nothing is logged because no new child is ever spawned. Production sat
in exactly that state for ~30 minutes on 2026-09-13 before a human noticed.

Serving SSE from this process deletes the layer that could die unnoticed:
the listening socket and the MCP server are the same process now, so
``Restart=always`` means what it says. The sd_notify watchdog below covers
the remaining case that no socket-level check can see -- an event loop that
is alive but wedged -- because the ping is sent *from* that loop.

stdio remains the default transport: it is what local clients and the test
suite use. Only the deployed unit passes ``--transport sse``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import socket
import time
from typing import Any, AsyncIterator, Callable, Optional

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8112
MESSAGE_ENDPOINT = "/messages/"


# === CLI / configuration ===


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse server command line arguments.

    Defaults come from the environment so the systemd unit can be steered
    from an ``EnvironmentFile`` without editing ``ExecStart``.
    """
    parser = argparse.ArgumentParser(
        prog="spirrow-prismind",
        description="Spirrow-Prismind MCP server",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse"),
        default=os.environ.get("PRISMIND_TRANSPORT", "stdio"),
        help="Transport to serve. Default: stdio (env: PRISMIND_TRANSPORT)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("PRISMIND_HOST", DEFAULT_HOST),
        help=(
            "Bind address for --transport sse. Default: 127.0.0.1 "
            "(env: PRISMIND_HOST). The MCP endpoint is unauthenticated, so "
            "binding beyond loopback exposes every tool to the network."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PRISMIND_PORT", DEFAULT_PORT)),
        help=f"Port for --transport sse. Default: {DEFAULT_PORT} (env: PRISMIND_PORT)",
    )
    return parser.parse_args(argv)


# === systemd integration ===


def sd_notify(state: str) -> bool:
    """Send a notification datagram to systemd.

    Returns True when the message was sent, False when there is nothing to
    notify (no ``NOTIFY_SOCKET``, i.e. not running under ``Type=notify``).
    Failures are logged and swallowed: losing a watchdog ping must never
    take the server down.
    """
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False

    # "@" is systemd's spelling of the abstract namespace's leading NUL.
    if address.startswith("@"):
        address = "\0" + address[1:]

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(state.encode("utf-8"))
        return True
    except OSError as exc:
        logger.warning("sd_notify(%r) failed: %s", state, exc)
        return False


def watchdog_interval_seconds() -> Optional[float]:
    """Ping interval implied by systemd's ``WatchdogSec``, or None.

    systemd exports the *deadline* as ``WATCHDOG_USEC``; the documented
    convention is to ping at half of it. ``WATCHDOG_PID``, when present,
    scopes the watchdog to one process -- respect it so a forked child does
    not keep the unit alive on the main process's behalf.
    """
    raw = os.environ.get("WATCHDOG_USEC")
    if not raw:
        return None

    watchdog_pid = os.environ.get("WATCHDOG_PID")
    if watchdog_pid and watchdog_pid != str(os.getpid()):
        return None

    try:
        usec = int(raw)
    except ValueError:
        logger.warning("ignoring malformed WATCHDOG_USEC=%r", raw)
        return None

    if usec <= 0:
        return None

    return usec / 2 / 1_000_000


async def watchdog_pinger(
    interval: float,
    *,
    notify: Callable[[str], bool] = sd_notify,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> None:
    """Ping the systemd watchdog forever, from the serving event loop.

    Running on the same loop that answers requests is the whole point: if
    the loop wedges, the pings stop and systemd restarts the unit.
    """
    logger.info("systemd watchdog enabled, pinging every %.1fs", interval)
    while True:
        notify("WATCHDOG=1")
        await sleep(interval)


# === SSE application ===


def build_sse_app(
    mcp_server: Server,
    *,
    tool_count: int,
    started_at: Optional[float] = None,
) -> Starlette:
    """Build the ASGI app that serves this MCP server over SSE.

    Routes:
      ``GET  /sse``       -- opens a session, streams server messages
      ``POST /messages/`` -- client messages for an established session
      ``GET  /health``    -- liveness for the healthcheck timer and dashboards

    ``/health`` deliberately touches nothing but this process: it reports
    that the event loop is serving HTTP and how many MCP sessions are open,
    and never reaches for Google Drive, RAG or Memory. Upstream reachability
    is a separate question from "is prismind serving", and conflating them
    is how a health check starts flapping on someone else's outage.
    """
    started = time.monotonic() if started_at is None else started_at
    sse = SseServerTransport(MESSAGE_ENDPOINT)

    async def handle_sse(request: Any) -> Response:
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp_server.run(
                streams[0],
                streams[1],
                mcp_server.create_initialization_options(),
            )
        # connect_sse yields on client disconnect; Starlette still needs a
        # response object here or the ASGI cycle raises TypeError: NoneType.
        return Response()

    async def handle_health(request: Any) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "transport": "sse",
                "pid": os.getpid(),
                "uptime_seconds": round(time.monotonic() - started, 3),
                "tool_count": tool_count,
                "active_sessions": _active_sessions(sse),
            }
        )

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        interval = watchdog_interval_seconds()
        pinger: Optional[asyncio.Task[None]] = None
        if interval:
            pinger = asyncio.create_task(watchdog_pinger(interval))

        sd_notify("READY=1")
        try:
            yield
        finally:
            sd_notify("STOPPING=1")
            if pinger is not None:
                pinger.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pinger

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Route("/health", endpoint=handle_health, methods=["GET"]),
            Mount(MESSAGE_ENDPOINT, app=sse.handle_post_message),
        ],
        lifespan=lifespan,
    )


def _active_sessions(sse: SseServerTransport) -> int:
    """Number of open SSE sessions.

    Reads a private attribute of the SDK transport; kept behind getattr so a
    future SDK rename degrades the health payload instead of 500-ing it.
    """
    writers = getattr(sse, "_read_stream_writers", None)
    if writers is None:
        return -1
    return len(writers)


async def serve_sse(mcp_server: Server, *, host: str, port: int, tool_count: int) -> None:
    """Serve the MCP server over SSE until the process is stopped."""
    # Imported here so stdio runs (tests, local clients) never pay for it.
    import uvicorn

    app = build_sse_app(mcp_server, tool_count=tool_count)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        # The app configures logging from config.toml; letting uvicorn
        # install its own dictConfig would drop those handlers.
        log_config=None,
        access_log=False,
    )
    logger.info("serving MCP over SSE on http://%s:%d/sse", host, port)
    await uvicorn.Server(config).serve()
