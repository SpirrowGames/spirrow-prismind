"""Knowledge ids must stay unique even when the clock does not advance.

Regression for T-knowledge-id-timestamp-collision: the id used to be built
from ``datetime.now()`` alone, so two adds within one clock tick (common on
Windows) produced the same id.
"""

import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from spirrow_prismind.integrations.rag_client import (
    RAGClient,
    RAGOperationResult,
    _new_knowledge_id,
)
from tests.mocks.mock_rag import MockRAGClient

KNOWLEDGE_ID_RE = re.compile(r"^knowledge:\d{20}-[0-9a-f]{8}$")
FROZEN_UTC = datetime(2026, 10, 3, 12, 0, 0, 123456, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    """A real ``datetime`` subclass whose ``now()`` never advances.

    ``datetime.datetime`` is a C built-in and cannot be patched in place, so
    the module-level ``datetime`` name in rag_client is replaced with this
    subclass. Unlike a MagicMock it keeps every other class behaviour
    (``fromisoformat``, arithmetic, ``isinstance`` on its own results).
    ``now(tz)`` returns the frozen instant converted to ``tz``, so a call that
    asks for a different zone yields a different wall-clock prefix.
    """

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            # Naive local time, deliberately far from UTC, so a regression
            # back to datetime.now() shows up as a different prefix.
            return (FROZEN_UTC + timedelta(hours=9)).replace(tzinfo=None)
        return FROZEN_UTC.astimezone(tz)


def _frozen_clock():
    p = patch(
        "spirrow_prismind.integrations.rag_client.datetime", _FrozenDatetime
    )
    p.start()
    return p


def test_new_knowledge_id_format():
    assert KNOWLEDGE_ID_RE.match(_new_knowledge_id())


def test_add_knowledge_ids_differ_when_clock_is_frozen():
    client = RAGClient(base_url="http://rag.invalid")
    p = _frozen_clock()
    try:
        with patch.object(
            RAGClient,
            "add_document",
            side_effect=lambda doc_id, content, metadata: RAGOperationResult(
                success=True, doc_id=doc_id
            ),
        ) as add_doc:
            r1 = client.add_knowledge("first", "技術Tips", ["a"])
            r2 = client.add_knowledge("second", "技術Tips", ["b"])
    finally:
        p.stop()

    ids = [c.args[0] for c in add_doc.call_args_list]
    assert len(ids) == 2
    assert ids[0] != ids[1]
    assert [r1.doc_id, r2.doc_id] == ids
    for doc_id in ids:
        assert KNOWLEDGE_ID_RE.match(doc_id)
        # Timestamp prefix is the UTC instant, not the host's local time.
        assert doc_id.startswith("knowledge:20261003120000123456-")


def test_mock_uses_production_id_shape_and_keeps_both_entries():
    rag = MockRAGClient()
    p = _frozen_clock()
    try:
        r1 = rag.add_knowledge("first", "技術Tips", ["a"])
        r2 = rag.add_knowledge("second", "技術Tips", ["b"])
    finally:
        p.stop()

    assert r1.doc_id != r2.doc_id
    assert KNOWLEDGE_ID_RE.match(r1.doc_id)
    assert KNOWLEDGE_ID_RE.match(r2.doc_id)
    assert rag.get_document(r1.doc_id).content == "first"
    assert rag.get_document(r2.doc_id).content == "second"
