"""Tests for ``spirrow_prismind.transport``.

These pin the deployment contract, not an implementation detail: the unit
file is ``Type=notify`` with ``WatchdogSec``, so if ``READY=1`` stops being
sent the service never comes up, and if the watchdog ping stops being sent
from the serving loop systemd kills it every minute. Both are silent in
tests unless asserted here.
"""

from __future__ import annotations

import asyncio
import os
import socket

import pytest
from mcp.server import Server
from starlette.testclient import TestClient

from spirrow_prismind import transport

# === CLI ===


def test_defaults_to_stdio_on_loopback():
    args = transport.parse_args([])
    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 8112


def test_flags_override_defaults():
    args = transport.parse_args(["--transport", "sse", "--host", "0.0.0.0", "--port", "9999"])
    assert (args.transport, args.host, args.port) == ("sse", "0.0.0.0", 9999)


def test_environment_supplies_defaults(monkeypatch):
    monkeypatch.setenv("PRISMIND_TRANSPORT", "sse")
    monkeypatch.setenv("PRISMIND_HOST", "10.0.0.1")
    monkeypatch.setenv("PRISMIND_PORT", "8200")
    args = transport.parse_args([])
    assert (args.transport, args.host, args.port) == ("sse", "10.0.0.1", 8200)


def test_rejects_unknown_transport():
    with pytest.raises(SystemExit):
        transport.parse_args(["--transport", "carrier-pigeon"])


# === sd_notify ===


def test_sd_notify_is_a_noop_without_notify_socket(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert transport.sd_notify("READY=1") is False


def test_sd_notify_sends_datagram(tmp_path, monkeypatch):
    path = str(tmp_path / "notify.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    listener.bind(path)
    listener.settimeout(5)
    monkeypatch.setenv("NOTIFY_SOCKET", path)
    try:
        assert transport.sd_notify("READY=1") is True
        assert listener.recv(64) == b"READY=1"
    finally:
        listener.close()


def test_sd_notify_swallows_dead_socket(tmp_path, monkeypatch):
    # A missing socket must not propagate: losing a ping is survivable,
    # crashing the server because systemd went away is not.
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "gone.sock"))
    assert transport.sd_notify("WATCHDOG=1") is False


# === watchdog ===


def test_watchdog_interval_is_half_the_deadline(monkeypatch):
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")
    monkeypatch.delenv("WATCHDOG_PID", raising=False)
    assert transport.watchdog_interval_seconds() == 30.0


def test_watchdog_disabled_without_env(monkeypatch):
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    assert transport.watchdog_interval_seconds() is None


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number", ""])
def test_watchdog_ignores_unusable_values(monkeypatch, value):
    monkeypatch.setenv("WATCHDOG_USEC", value)
    monkeypatch.delenv("WATCHDOG_PID", raising=False)
    assert transport.watchdog_interval_seconds() is None


def test_watchdog_ignored_when_scoped_to_another_pid(monkeypatch):
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")
    monkeypatch.setenv("WATCHDOG_PID", str(os.getpid() + 1))
    assert transport.watchdog_interval_seconds() is None


async def test_watchdog_pinger_pings_on_every_tick():
    sent: list[str] = []
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 3:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await transport.watchdog_pinger(
            15.0,
            notify=lambda state: sent.append(state) or True,
            sleep=fake_sleep,
        )

    assert sent == ["WATCHDOG=1"] * 3
    assert slept == [15.0, 15.0, 15.0]


# === SSE application ===


@pytest.fixture
def app():
    return transport.build_sse_app(Server("test-prismind"), tool_count=46)


def test_health_reports_serving_state(app):
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["transport"] == "sse"
    assert body["tool_count"] == 46
    assert body["active_sessions"] == 0
    assert body["pid"] == os.getpid()
    assert body["uptime_seconds"] >= 0


def test_routes_match_what_clients_expect(app):
    paths = {getattr(route, "path", None) for route in app.routes}
    # mcp's sse_client hits /sse and is then told where to POST; the mount
    # path is part of the wire contract with every existing consumer.
    assert "/sse" in paths
    assert "/messages" in paths or "/messages/" in paths
    assert "/health" in paths


def test_lifespan_announces_readiness_and_stop(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(transport, "sd_notify", lambda state: sent.append(state) or True)
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)

    with TestClient(transport.build_sse_app(Server("test-prismind"), tool_count=1)) as client:
        client.get("/health")

    assert sent == ["READY=1", "STOPPING=1"]


def test_lifespan_starts_watchdog_when_systemd_asks(monkeypatch):
    sent: list[str] = []
    intervals: list[float] = []
    monkeypatch.setattr(transport, "sd_notify", lambda state: sent.append(state) or True)

    async def fake_pinger(interval: float) -> None:
        intervals.append(interval)
        transport.sd_notify("WATCHDOG=1")
        # Outlive the request loop so shutdown has something to cancel.
        await asyncio.sleep(3600)

    monkeypatch.setattr(transport, "watchdog_pinger", fake_pinger)
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")
    monkeypatch.delenv("WATCHDOG_PID", raising=False)

    with TestClient(transport.build_sse_app(Server("test-prismind"), tool_count=1)) as client:
        for _ in range(20):
            client.get("/health")
            if intervals:
                break

    assert intervals == [30.0], "watchdog was not started on the serving loop"
    assert sent[0] == "READY=1"
    assert "WATCHDOG=1" in sent
    assert sent[-1] == "STOPPING=1"
