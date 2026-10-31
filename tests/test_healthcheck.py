"""Tests for ``scripts/healthcheck.py``.

The probe is what stands between "MCP is broken" and someone noticing by
hand 30 minutes later, and it is also the only thing on the box allowed to
restart the server unit. The restart throttle is therefore load-bearing in
both directions: too eager and a dependency outage becomes a restart loop
that scrolls the real error out of the journal, too lazy and the outage it
exists to end just continues.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

# Make the scripts directory importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import healthcheck


@pytest.fixture(autouse=True)
def _no_network_health(monkeypatch):
    # run() reads /health by default; no test may reach a real socket.
    monkeypatch.setattr(healthcheck, "fetch_health", lambda url, timeout: None)
    monkeypatch.setattr(
        healthcheck.run, "__kwdefaults__",
        {**healthcheck.run.__kwdefaults__, "health_fn": lambda url, timeout: None},
    )


def _health(busy=False, tool=None, seconds=0.0):
    """health_fn stub returning one /health payload."""
    calls = []

    def health_fn(url, timeout):
        calls.append(url)
        return {
            "status": "ok",
            "tool_executor": {"busy": busy, "current_tool": tool, "busy_seconds": seconds},
        }

    health_fn.calls = calls
    return health_fn


def _restart_events(caplog):
    return [
        json.loads(r.getMessage().split("RESTART_EVENT ", 1)[1])
        for r in caplog.records
        if r.getMessage().startswith("RESTART_EVENT ")
    ]


def _probe(*results):
    """Probe stub returning the given results in order."""
    calls = []
    queue = list(results)

    def probe_fn(url, timeout, expected):
        calls.append((url, timeout, expected))
        return queue.pop(0) if queue else (False, "exhausted")

    probe_fn.calls = calls
    return probe_fn


# === exit status ===


def test_healthy_probe_exits_zero_without_retrying():
    probe_fn = _probe((True, "46 tools"))
    code = healthcheck.run([], probe_fn=probe_fn, restart_fn=lambda unit: 0)
    assert code == 0
    assert len(probe_fn.calls) == 1


def test_unhealthy_probe_exits_nonzero():
    code = healthcheck.run(
        ["--attempts", "1"],
        probe_fn=_probe((False, "Not connected")),
        restart_fn=lambda unit: 0,
    )
    assert code == 1


def test_second_attempt_can_clear_a_transient_failure():
    probe_fn = _probe((False, "timeout"), (True, "46 tools"))
    restarted = []
    code = healthcheck.run(
        ["--restart-unit", "spirrow-prismind.service"],
        probe_fn=probe_fn,
        restart_fn=lambda unit: restarted.append(unit) or 0,
        sleep_fn=lambda _seconds: None,
    )
    assert code == 0
    assert restarted == [], "a single failed probe must not restart production"


def test_expected_tools_default_to_the_set_magickit_requires():
    probe_fn = _probe((True, "ok"))
    healthcheck.run([], probe_fn=probe_fn, restart_fn=lambda unit: 0)
    _url, _timeout, expected = probe_fn.calls[0]
    assert set(expected) == {"search_knowledge", "add_knowledge", "list_projects"}


def test_expect_tool_flag_overrides_the_default_set():
    probe_fn = _probe((True, "ok"))
    healthcheck.run(
        ["--expect-tool", "get_document", "--expect-tool", "list_documents"],
        probe_fn=probe_fn,
        restart_fn=lambda unit: 0,
    )
    _url, _timeout, expected = probe_fn.calls[0]
    assert set(expected) == {"get_document", "list_documents"}


# === restart behaviour ===


def test_restart_is_requested_once_every_attempt_failed(tmp_path):
    restarted = []
    stamp = tmp_path / "stamp"
    code = healthcheck.run(
        [
            "--attempts", "2",
            "--retry-delay", "0",
            "--restart-unit", "spirrow-prismind.service",
            "--stamp", str(stamp),
        ],
        probe_fn=_probe((False, "Not connected"), (False, "Not connected")),
        restart_fn=lambda unit: restarted.append(unit) or 0,
        sleep_fn=lambda _seconds: None,
    )
    assert code == 1
    assert restarted == ["spirrow-prismind.service"]
    assert stamp.exists(), "restart must be stamped or the throttle cannot work"


def test_no_restart_unit_means_report_only(tmp_path):
    restarted = []
    stamp = tmp_path / "stamp"
    healthcheck.run(
        ["--attempts", "1", "--stamp", str(stamp)],
        probe_fn=_probe((False, "Not connected")),
        restart_fn=lambda unit: restarted.append(unit) or 0,
    )
    assert restarted == []
    assert not stamp.exists()


def test_restart_is_throttled_by_a_recent_stamp(tmp_path):
    stamp = tmp_path / "stamp"
    stamp.touch()
    restarted = []
    code = healthcheck.run(
        [
            "--attempts", "1",
            "--restart-unit", "spirrow-prismind.service",
            "--stamp", str(stamp),
            "--min-restart-interval", "600",
        ],
        probe_fn=_probe((False, "Not connected")),
        restart_fn=lambda unit: restarted.append(unit) or 0,
    )
    assert code == 1
    assert restarted == [], "restart loop guard did not hold"


def test_throttle_expires(tmp_path):
    import os
    import time

    stamp = tmp_path / "stamp"
    stamp.touch()
    old = time.time() - 3600
    os.utime(stamp, (old, old))

    restarted = []
    healthcheck.run(
        [
            "--attempts", "1",
            "--restart-unit", "spirrow-prismind.service",
            "--stamp", str(stamp),
            "--min-restart-interval", "600",
        ],
        probe_fn=_probe((False, "Not connected")),
        restart_fn=lambda unit: restarted.append(unit) or 0,
    )
    assert restarted == ["spirrow-prismind.service"]


def test_may_restart_without_any_previous_stamp(tmp_path):
    assert healthcheck.may_restart(tmp_path / "never-written", 600.0) is True


# === error reporting ===


def test_probe_unwraps_exception_groups(monkeypatch):
    # anyio task groups wrap the real error; a health log that only says
    # "ExceptionGroup: unhandled errors in a TaskGroup" is what made the
    # original outage take 30 minutes to diagnose.
    def boom(*_args, **_kwargs):
        raise BaseExceptionGroup(
            "unhandled errors in a TaskGroup",
            [BaseExceptionGroup("inner", [RuntimeError("Not connected")])],
        )

    monkeypatch.setattr(healthcheck, "_probe_async", boom)
    healthy, detail = healthcheck.probe("http://127.0.0.1:8112/sse", 1.0, ("x",))
    assert healthy is False
    assert detail == "RuntimeError: Not connected"


# === tool worker occupancy (/health tool_executor) ===

_ARGV = [
    "--attempts", "2",
    "--retry-delay", "0",
    "--restart-unit", "spirrow-prismind.service",
]


def test_health_url_is_derived_from_the_sse_url():
    assert healthcheck.health_url_for("http://127.0.0.1:8113/sse") == "http://127.0.0.1:8113/health"


def test_a_stuck_tool_worker_restarts_even_though_mcp_answers(tmp_path, caplog):
    # The 2026-09-14 shape: tools/list is fine, the worker is not.
    caplog.set_level(logging.INFO, logger="prismind.healthcheck")
    restarted = []
    health_fn = _health(busy=True, tool="search_knowledge", seconds=901.5)
    code = healthcheck.run(
        _ARGV + ["--stamp", str(tmp_path / "stamp")],
        probe_fn=_probe((True, "46 tools"), (True, "46 tools")),
        health_fn=health_fn,
        restart_fn=lambda unit: restarted.append(unit) or 0,
        notify_fn=lambda event: None,
        sleep_fn=lambda _s: None,
    )
    assert code == 1
    assert restarted == ["spirrow-prismind.service"]
    assert health_fn.calls == ["http://127.0.0.1:8112/health"] * 2
    [event] = _restart_events(caplog)
    assert event["reason"] == "tool_busy"
    assert event["current_tool"] == "search_knowledge"
    assert event["busy_seconds"] == 901.5
    assert event["restarted"] is True
    assert event["systemctl_rc"] == 0


def test_a_busy_worker_under_the_threshold_is_healthy(tmp_path):
    restarted = []
    code = healthcheck.run(
        _ARGV + ["--stamp", str(tmp_path / "stamp")],
        probe_fn=_probe((True, "46 tools")),
        health_fn=_health(busy=True, tool="sync_catalog", seconds=599.0),
        restart_fn=lambda unit: restarted.append(unit) or 0,
    )
    assert code == 0
    assert restarted == []


def test_max_tool_busy_defaults_to_600_and_can_be_lowered(tmp_path):
    assert healthcheck.parse_args([]).max_tool_busy == 600.0
    restarted = []
    healthcheck.run(
        _ARGV + ["--stamp", str(tmp_path / "stamp"), "--max-tool-busy", "30"],
        probe_fn=_probe((True, "ok"), (True, "ok")),
        health_fn=_health(busy=True, tool="get_identity", seconds=31.0),
        restart_fn=lambda unit: restarted.append(unit) or 0,
        notify_fn=lambda event: None,
        sleep_fn=lambda _s: None,
    )
    assert restarted == ["spirrow-prismind.service"]


def test_one_stuck_reading_does_not_restart_when_the_retry_is_clear(tmp_path):
    readings = iter([
        {"tool_executor": {"busy": True, "current_tool": "x", "busy_seconds": 700.0}},
        {"tool_executor": {"busy": False, "current_tool": None, "busy_seconds": 0.0}},
    ])
    restarted = []
    code = healthcheck.run(
        _ARGV + ["--stamp", str(tmp_path / "stamp")],
        probe_fn=_probe((True, "ok"), (True, "ok")),
        health_fn=lambda url, timeout: next(readings),
        restart_fn=lambda unit: restarted.append(unit) or 0,
        sleep_fn=lambda _s: None,
    )
    assert code == 0
    assert restarted == []


@pytest.mark.parametrize("payload", [None, {"status": "ok"}, {"tool_executor": None}])
def test_health_without_tool_executor_leaves_the_mcp_verdict_alone(tmp_path, payload):
    # An older server, or an unreadable /health, cannot show a stuck worker
    # and must not be a restart reason of its own.
    restarted = []
    code = healthcheck.run(
        _ARGV + ["--stamp", str(tmp_path / "stamp")],
        probe_fn=_probe((True, "ok")),
        health_fn=lambda url, timeout: payload,
        restart_fn=lambda unit: restarted.append(unit) or 0,
    )
    assert code == 0
    assert restarted == []


# === RESTART_EVENT and notify_fn ===


def test_mcp_failure_event_still_names_the_tool_on_the_worker(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="prismind.healthcheck")
    notified = []
    healthcheck.run(
        _ARGV + ["--stamp", str(tmp_path / "stamp")],
        probe_fn=_probe((False, "Not connected"), (False, "Not connected")),
        health_fn=_health(busy=True, tool="get_document", seconds=12.0),
        restart_fn=lambda unit: 0,
        notify_fn=notified.append,
        sleep_fn=lambda _s: None,
    )
    [event] = _restart_events(caplog)
    assert event["reason"] == "mcp_probe"
    assert event["current_tool"] == "get_document"
    assert notified == [event]


def test_throttled_restart_is_still_an_event_and_a_notification(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="prismind.healthcheck")
    stamp = tmp_path / "stamp"
    stamp.touch()
    restarted, notified = [], []
    code = healthcheck.run(
        _ARGV + ["--stamp", str(stamp)],
        probe_fn=_probe((True, "ok"), (True, "ok")),
        health_fn=_health(busy=True, tool="search_knowledge", seconds=4000.0),
        restart_fn=lambda unit: restarted.append(unit) or 0,
        notify_fn=notified.append,
        sleep_fn=lambda _s: None,
    )
    assert code == 1
    assert restarted == []
    [event] = _restart_events(caplog)
    assert event["restarted"] is False
    assert event["systemctl_rc"] is None
    assert event["reason"] == "tool_busy"
    assert notified == [event]


def test_event_carries_a_failed_systemctl_status(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="prismind.healthcheck")
    healthcheck.run(
        _ARGV + ["--stamp", str(tmp_path / "stamp")],
        probe_fn=_probe((False, "x"), (False, "x")),
        restart_fn=lambda unit: 5,
        notify_fn=lambda event: None,
        sleep_fn=lambda _s: None,
    )
    [event] = _restart_events(caplog)
    assert event["restarted"] is True
    assert event["systemctl_rc"] == 5


def test_a_failing_notification_does_not_stop_the_restart(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="prismind.healthcheck")

    def broken_notify(event):
        raise ConnectionError("composer unreachable")

    restarted = []
    code = healthcheck.run(
        _ARGV + ["--stamp", str(tmp_path / "stamp")],
        probe_fn=_probe((False, "x"), (False, "x")),
        restart_fn=lambda unit: restarted.append(unit) or 0,
        notify_fn=broken_notify,
        sleep_fn=lambda _s: None,
    )
    assert code == 1
    assert restarted == ["spirrow-prismind.service"]
    assert len(_restart_events(caplog)) == 1
    assert any("operator notification failed" in r.getMessage() for r in caplog.records)


def test_report_only_runs_emit_no_restart_event(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="prismind.healthcheck")
    notified = []
    healthcheck.run(
        ["--attempts", "1", "--stamp", str(tmp_path / "stamp")],
        probe_fn=_probe((False, "x")),
        notify_fn=notified.append,
    )
    assert _restart_events(caplog) == []
    assert notified == []


def test_default_notification_writes_to_the_journal(caplog):
    caplog.set_level(logging.INFO, logger="prismind.healthcheck")
    healthcheck.notify_journal(
        {"reason": "tool_busy", "current_tool": "t", "busy_seconds": 700.0, "restarted": True}
    )
    assert any(r.getMessage().startswith("OPERATOR_NOTICE") for r in caplog.records)
