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

The MCP probe cannot see the 2026-09-14 shape, though: one tool call that
never returns holds the server's single tool worker, every call queued
behind it (``get_identity`` included) waits forever, and the event loop --
and so ``tools/list``, the watchdog and ``/health`` -- keeps answering. So
each attempt also reads ``/health`` and treats a tool worker that has been
busy for longer than ``--max-tool-busy`` seconds as unhealthy. ``/health``
reports that from the server's memory; the probe never calls a tool, so an
upstream outage cannot turn into a Prismind restart loop.

Every restart, and every restart the throttle suppresses, is logged as one
``RESTART_EVENT {json}`` line (``journalctl -t prismind-healthcheck -g
RESTART_EVENT``) and handed to ``notify_fn``.

Run from the systemd timer in ``deploy/``:

    python scripts/healthcheck.py --restart-unit spirrow-prismind.service

Exit status is 0 when healthy and 1 when not, so a failing probe also shows
up in ``systemctl --failed`` even on the runs where a restart is suppressed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

logger = logging.getLogger("prismind.healthcheck")

DEFAULT_URL = "http://127.0.0.1:8112/sse"
DEFAULT_STAMP = Path("/run/spirrow-prismind-healthcheck.stamp")

# The set magickit's PrismindAdapter.health_check() requires. If these are
# reachable the service is useful to its callers; a longer list would only
# add ways for a tool rename to page someone at 3am.
DEFAULT_EXPECTED_TOOLS = ("search_knowledge", "add_knowledge", "list_projects")

# Long enough that a legitimate long call is not mistaken for a hang, short
# enough against a 15.5-hour one: worst-case detection is this plus one
# timer period plus the retries, about 12 minutes.
DEFAULT_MAX_TOOL_BUSY = 600.0

REASON_MCP_PROBE = "mcp_probe"
REASON_TOOL_BUSY = "tool_busy"


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


def health_url_for(url: str) -> str:
    """The server's ``/health`` URL, derived from its SSE URL."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/health", "", ""))


def fetch_health(url: str, timeout: float) -> Optional[dict[str, Any]]:
    """GET ``/health``; None when it cannot be read or parsed."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - "could not read" is one outcome
        logger.warning("could not read %s: %s", url, _describe(exc))
        return None


def tool_executor_state(health: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The ``tool_executor`` block of a /health payload, if it carries one."""
    if not isinstance(health, dict):
        return None
    state = health.get("tool_executor")
    return state if isinstance(state, dict) else None


def is_stuck(worker: Optional[dict[str, Any]], max_busy: float) -> bool:
    """Whether the tool worker has been on one call for longer than max_busy."""
    if not worker or not worker.get("busy"):
        return False
    try:
        return float(worker.get("busy_seconds") or 0.0) > max_busy
    except (TypeError, ValueError):
        return False


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


def restart_unit(unit: str) -> int:
    """Restart a systemd unit. Returns systemctl's exit status (0 = success)."""
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
    return completed.returncode


# === restart events and operator notification ===


def emit_restart_event(event: dict[str, Any]) -> None:
    """Write the event as one journal line.

    This line is the restart history; there is deliberately no separate
    file. Read it back with ``journalctl -t prismind-healthcheck -g
    RESTART_EVENT`` (the unit sets that SyslogIdentifier). It survives a
    reboot only on a persistent journal.
    """
    logger.warning("RESTART_EVENT %s", json.dumps(event, ensure_ascii=False, sort_keys=True))


def notify_journal(event: dict[str, Any]) -> None:
    """Default operator notification: the journal only.

    Intended reader: the operator. No route from this host to the composer
    exists in this repository, so the notice stays in the journal next to
    the RESTART_EVENT line until one is wired in. Wiring it builds a new
    delivery path and is a separate task; pass a different ``notify_fn`` to
    ``run()`` to deliver elsewhere.
    """
    action = "restarted" if event.get("restarted") else "restart suppressed by throttle"
    logger.warning(
        "OPERATOR_NOTICE prismind %s: reason=%s current_tool=%s busy_seconds=%s",
        action, event.get("reason"), event.get("current_tool"), event.get("busy_seconds"),
    )


def _notify(notify_fn: Callable[[dict[str, Any]], None], event: dict[str, Any]) -> None:
    # The notification reports the restart; it must never stand in its way.
    try:
        notify_fn(event)
    except Exception as exc:  # noqa: BLE001
        logger.warning("operator notification failed: %s", _describe(exc))


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
    parser.add_argument(
        "--max-tool-busy", type=float, default=DEFAULT_MAX_TOOL_BUSY,
        help="Seconds the tool worker may stay on one call before the server "
             "counts as unhealthy (read from /health). Default: 600",
    )
    parser.add_argument(
        "--health-url", default=None, metavar="URL",
        help="The server's /health URL. Default: --url with the path /health.",
    )
    return parser.parse_args(argv)


def run(
    argv: Optional[Sequence[str]] = None,
    *,
    probe_fn: Callable[..., tuple[bool, str]] = probe,
    health_fn: Callable[[str, float], Optional[dict[str, Any]]] = fetch_health,
    restart_fn: Callable[[str], int] = restart_unit,
    notify_fn: Callable[[dict[str, Any]], None] = notify_journal,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    args = parse_args(argv)
    expected: Iterable[str] = args.expect_tools or DEFAULT_EXPECTED_TOOLS
    health_url = args.health_url or health_url_for(args.url)

    detail = ""
    reason = REASON_MCP_PROBE
    worker: Optional[dict[str, Any]] = None
    for attempt in range(1, max(1, args.attempts) + 1):
        mcp_ok, detail = probe_fn(args.url, args.timeout, tuple(expected))
        # Read /health even when MCP failed: what the worker was stuck on is
        # the first thing the root-cause investigation needs.
        worker = tool_executor_state(health_fn(health_url, args.timeout))

        if not mcp_ok:
            reason = REASON_MCP_PROBE
        elif is_stuck(worker, args.max_tool_busy):
            reason = REASON_TOOL_BUSY
            detail = (
                f"tool worker on {worker.get('current_tool')} for "
                f"{float(worker.get('busy_seconds') or 0.0):.0f}s "
                f"(> {args.max_tool_busy:.0f}s)"
            )
        else:
            # A /health without tool_executor (an older server, or one that
            # could not be read) cannot show a stuck worker, so the MCP probe
            # alone decides; it does not count as a failure of its own.
            logger.info("healthy (%s)", detail)
            return 0

        logger.warning("probe %d/%d failed (%s): %s", attempt, args.attempts, reason, detail)
        if attempt < args.attempts:
            sleep_fn(args.retry_delay)

    logger.error("unhealthy after %d attempts (%s): %s", args.attempts, reason, detail)

    if not args.restart_unit:
        return 1

    event: dict[str, Any] = {
        "unit": args.restart_unit,
        "reason": reason,
        "detail": detail,
        "current_tool": (worker or {}).get("current_tool"),
        "busy_seconds": (worker or {}).get("busy_seconds"),
        "restarted": False,
        "systemctl_rc": None,
    }

    if not may_restart(args.stamp, args.min_restart_interval):
        age = seconds_since_last_restart(args.stamp)
        logger.error(
            "not restarting %s: last restart was %.0fs ago (< %.0fs). "
            "Repeated failures this close together are not a restartable fault.",
            args.restart_unit, age or 0.0, args.min_restart_interval,
        )
        emit_restart_event(event)
        _notify(notify_fn, event)
        return 1

    record_restart(args.stamp)
    event["systemctl_rc"] = restart_fn(args.restart_unit)
    event["restarted"] = True
    emit_restart_event(event)
    _notify(notify_fn, event)
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
