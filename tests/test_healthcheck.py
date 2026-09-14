"""Tests for ``scripts/healthcheck.py``.

The probe is what stands between "MCP is broken" and someone noticing by
hand 30 minutes later, and it is also the only thing on the box allowed to
restart the server unit. The restart throttle is therefore load-bearing in
both directions: too eager and a dependency outage becomes a restart loop
that scrolls the real error out of the journal, too lazy and the outage it
exists to end just continues.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the scripts directory importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import healthcheck


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
    code = healthcheck.run([], probe_fn=probe_fn, restart_fn=lambda unit: True)
    assert code == 0
    assert len(probe_fn.calls) == 1


def test_unhealthy_probe_exits_nonzero():
    code = healthcheck.run(
        ["--attempts", "1"],
        probe_fn=_probe((False, "Not connected")),
        restart_fn=lambda unit: True,
    )
    assert code == 1


def test_second_attempt_can_clear_a_transient_failure():
    probe_fn = _probe((False, "timeout"), (True, "46 tools"))
    restarted = []
    code = healthcheck.run(
        ["--restart-unit", "spirrow-prismind.service"],
        probe_fn=probe_fn,
        restart_fn=lambda unit: restarted.append(unit) or True,
        sleep_fn=lambda _seconds: None,
    )
    assert code == 0
    assert restarted == [], "a single failed probe must not restart production"


def test_expected_tools_default_to_the_set_magickit_requires():
    probe_fn = _probe((True, "ok"))
    healthcheck.run([], probe_fn=probe_fn, restart_fn=lambda unit: True)
    _url, _timeout, expected = probe_fn.calls[0]
    assert set(expected) == {"search_knowledge", "add_knowledge", "list_projects"}


def test_expect_tool_flag_overrides_the_default_set():
    probe_fn = _probe((True, "ok"))
    healthcheck.run(
        ["--expect-tool", "get_document", "--expect-tool", "list_documents"],
        probe_fn=probe_fn,
        restart_fn=lambda unit: True,
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
        restart_fn=lambda unit: restarted.append(unit) or True,
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
        restart_fn=lambda unit: restarted.append(unit) or True,
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
        restart_fn=lambda unit: restarted.append(unit) or True,
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
        restart_fn=lambda unit: restarted.append(unit) or True,
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
