"""ADR-2026-05-29-12 step (i) migration: null-update embodiment on existing identities.

Pre-ADR-12 identity records may carry a non-null ``embodiment`` value
(set when embodiment was a required enum field on ``upsert_identity``).
ADR-12 deprecates ``embodiment`` on the identity record in favor of
per-operation self-declaration. This one-shot script scans
``prismind:identity:*`` and rewrites each AI record with
``embodiment=None`` -- the persisted on-disk semantics for "no longer
declared on the identity record" (msg-325 §4).

Human records are left untouched. The response-side ``case 3`` omit
(``_identity_to_response_dict``) will hide the field from API
responses regardless of the on-disk value, but on-disk we still leave
the human record alone -- the migration is for *AI* records that had
a previously-meaningful embodiment value to be cleared.

Idempotent: re-running has no effect once values are already ``None``.

Usage::

    cd /home/sgadmin/services/spirrow/spirrow-prismind
    ./venv/bin/python scripts/migrate_embodiment_to_null.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the package importable when running from the repo root without install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spirrow_prismind.integrations.memory_client import (
    HUMAN_IDENTITY_NAMES,
    Identity,
    MemoryClient,
)


def migrate(client: MemoryClient) -> dict[str, int]:
    """Null-update embodiment on every AI identity record.

    Returns a counter dict: ``{"scanned": N, "updated": M, "human_skipped": H,
    "already_null": K}``. ``M + H + K`` should equal ``scanned``.
    """
    counters = {"scanned": 0, "updated": 0, "human_skipped": 0, "already_null": 0}

    for identity in client.list_identities():
        counters["scanned"] += 1

        if identity.identity_name in HUMAN_IDENTITY_NAMES:
            counters["human_skipped"] += 1
            continue

        if identity.embodiment is None:
            counters["already_null"] += 1
            continue

        # Construct a clean copy with embodiment cleared; preserve all
        # other fields including timestamps so the migration is
        # observable only on the deprecated column.
        cleared = Identity(
            identity_name=identity.identity_name,
            user=identity.user,
            allowed_roles=list(identity.allowed_roles),
            embodiment=None,
            independence_class=identity.independence_class,
            persona_description=identity.persona_description,
            created_at=identity.created_at,
            updated_at=identity.updated_at,
        )
        client.save_identity(cleared)
        counters["updated"] += 1

    return counters


if __name__ == "__main__":
    client = MemoryClient()
    result = migrate(client)
    print("ADR-12 embodiment null-update migration complete:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    client.close()
