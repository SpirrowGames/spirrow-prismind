#!/usr/bin/env python
"""Probe the deployed MCP endpoint and, optionally, restart a wedged unit.

This is the belt to ``--transport sse``'s braces. Serving SSE in-process
means a dead server can no longer hide behind a live proxy, and the systemd
watchdog catches a hung event loop -- but neither notices a server that
answers HTTP while its MCP layer is broken. That is the shape the
2026-09-13 outage took (``GET /sse`` returned 200 for 30 minutes while
every ``tools/list`` failed with ``Not connected``), so the probe speaks
MCP, not HTTP: connect, initialize, list tools, and require the tools that
callers actually depend on.

Run from the systemd timer in ``deploy/``:

    python scripts/healthcheck.py --restart-unit spirrow-prismind.service

Exit status is 0 when healthy and 1 when not, so a failing probe also shows
up in ``systemctl --failed`` even on the runs where a restart is suppressed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

logger = logging.getLogger("prismind.healthcheck")

DEFAULT_URL = "http://127.0.0.1:8112/sse"
DEFAULT_STAMP = Path("/run/spirrow-prismind-healthcheck.stamp")

# The set magickit's PrismindAdapter.health_check() requires. If these are
# reachable the service is useful to its callers; a longer list would only
# add ways for a tool rename to page someone at 3am.
DEFAULT_EXPECTED_TOOLS = ("search_knowledge", "add_knowledge", "list_projects")


# === probe ===


async def _probe_async(url: str, timeout: float, expected: Sequence[str]) -> tuple[bool, str]:
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client(url, sse_read_timeout=timeout) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

    names = {tool.name for tool in result.tools}
    missing = sorted(set(expected) - names)
    if missing:
        return False, f"missing tools: {', '.join(missing)} (saw {len(names)})"
    return True, f"{len(names)} tools"


def probe(url: str = DEFAULT_URL, timeout: float = 10.0,
          expected: Sequence[str] = DEFAULT_EXPECTED_TOOLS) -> tuple[bool, str]:
    """Return (healthy, detail). Any transport error counts as unhealthy."""
    try:
        return asyncio.run(_probe_async(url, timeout, expected))
    except Exception as exc:  # noqa: BLE001 - every failure mode is "unhealthy"
        # BaseExceptionGroup from anyio task groups stringifies uselessly on
        # its own, so unwrap it far enough to name the real error.
        return False, _describe(exc)


def _describe(exc: BaseException, depth: int = 0) -> str:
    inner = getattr(exc, "exceptions", None)
    if inner and depth < 4:
        return _describe(inner[0], depth + 1)
    return f"{type(exc).__name__}: {exc}"


# === restart throttling ===


def seconds_since_last_restart(stamp: Path, now: Optional[float] = None) -> Optional[float]:
    """Age of the restart stamp in seconds, or None when there is none."""
    try:
        mtime = stamp.stat().st_mtime
    except OSError:
        return None
    return (time.time() if now is None else now) - mtime


def may_restart(stamp: Path, min_interval: float, now: Optional[float] = None) -> bool:
    """Whether a restart is allowed, given the last one.

    Restarting on every failed probe turns one broken dependency into a
    restart loop that hides the real error from the journal, so a restart
    is only allowed once per ``min_interval``.
    """
    age = seconds_since_last_restart(stamp, now)
    return age is None or age >= min_interval


def record_restart(stamp: Path) -> None:
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
        os.utime(stamp, None)
    except OSError as exc:
        # Losing the stamp only weakens throttling; it must not abort the
        # restart we just decided to do.
        logger.warning("could not write restart stamp %s: %s", stamp, exc)


def restart_unit(unit: str) -> bool:
    """Restart a systemd unit. Returns True when systemctl reported success."""
    logger.warning("restarting %s", unit)
    completed = subprocess.run(
        ["systemctl", "restart", unit],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        logger.error(
            "systemctl restart %s failed (rc=%d): %s",
            unit, completed.returncode, (completed.stderr or "").strip(),
        )
        return False
    return True


# === entry point ===


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.environ.get("PRISMIND_HEALTHCHECK_URL", DEFAULT_URL))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--attempts", type=int, default=2,
        help="Consecutive failures required before acting. Default: 2",
    )
    parser.add_argument(
        "--retry-delay", type=float, default=5.0,
        help="Seconds between attempts. Default: 5",
    )
    parser.add_argument(
        "--expect-tool", action="append", dest="expect_tools", metavar="NAME",
        help="Tool that must be present (repeatable). Defaults to the set "
             "magickit's health check requires.",
    )
    parser.add_argument(
        "--restart-unit", default=None, metavar="UNIT",
        help="Restart this systemd unit when all attempts fail. Omit to only report.",
    )
    parser.add_argument("--stamp", type=Path, default=DEFAULT_STAMP)
    parser.add_argument(
        "--min-restart-interval", type=float, default=600.0,
        help="Minimum seconds between restarts. Default: 600",
    )
    return parser.parse_args(argv)


def run(
    argv: Optional[Sequence[str]] = None,
    *,
    probe_fn: Callable[..., tuple[bool, str]] = probe,
    restart_fn: Callable[[str], bool] = restart_unit,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    args = parse_args(argv)
    expected: Iterable[str] = args.expect_tools or DEFAULT_EXPECTED_TOOLS

    detail = ""
    for attempt in range(1, max(1, args.attempts) + 1):
        healthy, detail = probe_fn(args.url, args.timeout, tuple(expected))
        if healthy:
            logger.info("healthy (%s)", detail)
            return 0
        logger.warning("probe %d/%d failed: %s", attempt, args.attempts, detail)
        if attempt < args.attempts:
            sleep_fn(args.retry_delay)

    logger.error("unhealthy after %d attempts: %s", args.attempts, detail)

    if not args.restart_unit:
        return 1

    if not may_restart(args.stamp, args.min_restart_interval):
        age = seconds_since_last_restart(args.stamp)
        logger.error(
            "not restarting %s: last restart was %.0fs ago (< %.0fs). "
            "Repeated failures this close together are not a restartable fault.",
            args.restart_unit, age or 0.0, args.min_restart_interval,
        )
        return 1

    record_restart(args.stamp)
    restart_fn(args.restart_unit)
    return 1


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
