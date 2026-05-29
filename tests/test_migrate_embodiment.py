"""Tests for ``scripts/migrate_embodiment_to_null``.

The migration is run once after the ADR-12 PR-A deploy. It is small but
load-bearing -- existing AI identity records carry pre-ADR-12 embodiment
values (set when the field was a required enum) and the deprecation
contract is that the persisted on-disk value transitions to ``None``.
Pinned-by-test so the behavior cannot drift silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the scripts directory importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import migrate_embodiment_to_null

from spirrow_prismind.integrations.memory_client import Identity
from tests.mocks.mock_memory import MockMemoryClient


def _seed(client: MockMemoryClient, identity: Identity) -> None:
    client.save_identity(identity)


def test_migrate_clears_embodiment_on_ai_records():
    client = MockMemoryClient()
    _seed(client, Identity(
        identity_name="Heisenberg",
        user="sgadmin",
        allowed_roles=["implementer"],
        embodiment="terminal_coding_agent",
        independence_class="main-chain",
    ))
    _seed(client, Identity(
        identity_name="Bohr",
        user="sgadmin",
        allowed_roles=["proposer"],
        embodiment="web_ai_chat",
        independence_class="main-chain",
    ))

    result = migrate_embodiment_to_null.migrate(client)

    assert result == {
        "scanned": 2,
        "updated": 2,
        "human_skipped": 0,
        "already_null": 0,
    }
    assert client.get_identity("sgadmin", "Heisenberg").embodiment is None
    assert client.get_identity("sgadmin", "Bohr").embodiment is None


def test_migrate_skips_human_records():
    """Human records are left untouched on-disk (response-side omit
    is what hides the field for human, not on-disk null)."""
    client = MockMemoryClient()
    _seed(client, Identity(
        identity_name="human",
        user="sgadmin",
        allowed_roles=["human"],
        embodiment=None,
        independence_class="human",
    ))

    result = migrate_embodiment_to_null.migrate(client)
    assert result["scanned"] == 1
    assert result["human_skipped"] == 1
    assert result["updated"] == 0


def test_migrate_is_idempotent():
    """Running the migration twice should be a no-op the second time."""
    client = MockMemoryClient()
    _seed(client, Identity(
        identity_name="Einstein",
        user="sgadmin",
        allowed_roles=["naysayer"],
        embodiment="web_ai_chat",
        independence_class="independent",
    ))

    first = migrate_embodiment_to_null.migrate(client)
    second = migrate_embodiment_to_null.migrate(client)

    assert first["updated"] == 1
    assert second["updated"] == 0
    assert second["already_null"] == 1
