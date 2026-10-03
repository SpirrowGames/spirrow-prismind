"""Tests for search re-ranking through Lexora /v1/decide (T-decide-rerank)."""

import hashlib
import json
import logging

import httpx
import pytest

from spirrow_prismind.config import Config, RerankConfig
from spirrow_prismind.integrations.lexora_rerank import (
    HAS_ANSWER,
    LexoraReranker,
    question_name,
)
from spirrow_prismind.integrations.rag_client import RAGDocument, RAGSearchResult
from spirrow_prismind.tools.knowledge_tools import KnowledgeTools

# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeRAG:
    """RAG stub that returns a fixed list in a fixed order."""

    def __init__(self, ids):
        self.docs = [
            RAGDocument(
                doc_id=kid,
                content=f"content of {kid}",
                metadata={"category": "技術Tips", "project": "", "tags": []},
                score=1.0 - i * 0.01,
            )
            for i, kid in enumerate(ids)
        ]
        self.n_results_seen = []

    @property
    def is_available(self):
        return True

    def search_knowledge(self, query, category=None, project=None, tags=None, n_results=5):
        self.n_results_seen.append(n_results)
        docs = self.docs[:n_results]
        return RAGSearchResult(success=True, documents=docs, total_count=len(docs))


class FakeProjects:
    def get_current_project_id(self, user):
        return None


class FakeMemory:
    """Memory stub exposing a single recent cached entry."""

    def __init__(self, entries):
        self.entries = entries

    @property
    def is_available(self):
        return True

    def get(self, key):
        return None

    def get_recent_knowledge(self, project=None, limit=10):
        return list(self.entries)


class Lexora:
    """httpx.MockTransport handler that records requests."""

    def __init__(self, respond):
        self.respond = respond
        self.requests = []

    def __call__(self, request):
        self.requests.append(json.loads(request.content))
        return self.respond(request)


def jev_response(scores, has_answer=0.9, provider="jev", top_n=30):
    """A Lexora response; slots past len(scores) get 0.99 (must be ignored)."""
    answers = {question_name(i): {"noul": 0.99} for i in range(top_n)}
    for i, s in enumerate(scores):
        answers[question_name(i)] = {"noul": s}
    answers[HAS_ANSWER] = {"noul": has_answer}
    body = {
        "answers": answers,
        "provider": provider,
        "decision_id": "dec-123",
        "latency_ms": 5,
    }
    return lambda request: httpx.Response(200, json=body)


def make_reranker(handler, **overrides):
    cfg = RerankConfig(enabled=True, **overrides)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return LexoraReranker(cfg, http_client=client)


def make_tools(ids, reranker=None, memory=None):
    rag = FakeRAG(ids)
    tools = KnowledgeTools(
        rag_client=rag,
        project_tools=FakeProjects(),
        memory_client=memory,
        user_name="u",
        reranker=reranker,
    )
    return tools, rag


def ids_of(result):
    return [k.knowledge_id for k in result.knowledge]


def lexora_questions_hash(questions):
    """Same canonicalisation as lexora.decide.contract.compute_questions_hash.

    QuestionSpec.model_dump adds ``criteria: null`` when absent; replicate
    that so the hash matches what Lexora writes to its log.
    """
    normalised = {
        name: {"criteria": None, **q} if "criteria" not in q else q
        for name, q in questions.items()
    }
    payload = json.dumps(
        normalised, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


IDS = [f"k{i}" for i in range(12)]

# --------------------------------------------------------------------------
# D1: disabled == unchanged, zero HTTP calls
# --------------------------------------------------------------------------


class TestDisabled:
    def test_disabled_output_identical_and_no_http(self):
        baseline, _ = make_tools(IDS)
        handler = Lexora(jev_response([0.1] * 12))
        cfg = RerankConfig(enabled=False)
        reranker = LexoraReranker(
            cfg, http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        disabled, rag = make_tools(IDS, reranker=reranker)

        a = baseline.search_knowledge("q", limit=10)
        b = disabled.search_knowledge("q", limit=10)

        assert ids_of(a) == ids_of(b)
        assert a.message == b.message
        assert handler.requests == []
        assert rag.n_results_seen == [20]

    def test_default_config_is_disabled(self):
        assert Config().rerank.enabled is False
        assert Config._from_dict({}).rerank.enabled is False


# --------------------------------------------------------------------------
# D2: null provider / failures -> original order
# --------------------------------------------------------------------------


def _raise_connect(request):
    raise httpx.ConnectError("refused", request=request)


def _raise_timeout(request):
    raise httpx.ReadTimeout("slow", request=request)


FALLBACK_CASES = {
    "null_provider": jev_response([0.0] * 12, has_answer=0.0, provider="null"),
    "connect_error": _raise_connect,
    "timeout": _raise_timeout,
    "http_500": lambda r: httpx.Response(500, json={"detail": "boom"}),
    "not_json": lambda r: httpx.Response(200, content=b"<html>"),
    "missing_answers": lambda r: httpx.Response(
        200, json={"provider": "jev", "decision_id": "d", "latency_ms": 1}
    ),
    "missing_question": lambda r: httpx.Response(
        200,
        json={"provider": "jev", "decision_id": "d", "latency_ms": 1,
              "answers": {HAS_ANSWER: {"noul": 0.9}}},
    ),
    "noul_out_of_range": lambda r: httpx.Response(
        200,
        json={"provider": "jev", "decision_id": "d", "latency_ms": 1,
              "answers": {**{question_name(i): {"noul": 2.0} for i in range(30)},
                          HAS_ANSWER: {"noul": 0.9}}},
    ),
}


class TestFallback:
    @pytest.mark.parametrize("case", sorted(FALLBACK_CASES))
    def test_falls_back_to_search_order(self, case):
        baseline, _ = make_tools(IDS)
        expected = ids_of(baseline.search_knowledge("q", limit=10))

        handler = Lexora(FALLBACK_CASES[case])
        tools, _ = make_tools(IDS, reranker=make_reranker(handler))
        result = tools.search_knowledge("q", limit=10)

        assert result.success is True
        # No keep_k truncation and no has_answer filtering on fallback.
        assert ids_of(result) == expected
        assert len(handler.requests) == 1


# --------------------------------------------------------------------------
# D3: reranking, keep_k, cache position, padding, N > top_n, N == 0
# --------------------------------------------------------------------------


class TestRerank:
    def test_sorted_by_noul_desc_ties_stable_and_keep_k(self):
        scores = [0.1, 0.9, 0.5, 0.9, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.05, 0.5]
        handler = Lexora(jev_response(scores))
        tools, rag = make_tools(IDS, reranker=make_reranker(handler, keep_k=8))
        result = tools.search_knowledge("q", limit=10)

        # 0.9 tie: k1 before k3 (search order); 0.5 tie: k2 before k11.
        assert ids_of(result) == ["k1", "k3", "k9", "k8", "k7", "k2", "k11", "k6"]
        assert rag.n_results_seen == [30]  # max(top_n, limit*2)

    def test_limit_caps_below_keep_k(self):
        handler = Lexora(jev_response([0.1 * i for i in range(10)] + [0.0, 0.0]))
        tools, _ = make_tools(IDS, reranker=make_reranker(handler, keep_k=8))
        result = tools.search_knowledge("q", limit=3)
        assert ids_of(result) == ["k9", "k8", "k7"]

    def test_padding_slots_ignored(self):
        # 12 real candidates; slots 12..29 answer 0.99 and must not matter.
        handler = Lexora(jev_response([0.1] * 11 + [0.2]))
        tools, _ = make_tools(IDS, reranker=make_reranker(handler, keep_k=8))
        result = tools.search_knowledge("q", limit=10)
        assert ids_of(result)[0] == "k11"
        assert all(k in IDS for k in ids_of(result))
        assert len(result.knowledge) == 8

    def test_past_top_n_only_head_is_scored_and_kept(self):
        # N > top_n: only the first top_n are sent and scored; keep_k <= top_n
        # means the unscored rest never reaches the caller on this path.
        handler = Lexora(jev_response([0.1, 0.2, 0.3], top_n=3))
        reranker = make_reranker(handler, top_n=3, keep_k=3)
        outcome = reranker.rerank("q", IDS[:6], text_of=lambda k: k, id_of=lambda k: k)
        assert outcome.items == ["k2", "k1", "k0"]
        assert len(json.loads(handler.requests[0]["state"])["candidates"]) == 3

    def test_past_top_n_fallback_returns_everything(self):
        handler = Lexora(jev_response([0.1, 0.2, 0.3], provider="null", top_n=3))
        reranker = make_reranker(handler, top_n=3, keep_k=3)
        outcome = reranker.rerank("q", IDS[:6], text_of=lambda k: k, id_of=lambda k: k)
        assert outcome.items == IDS[:6]

    def test_zero_candidates_no_http(self):
        handler = Lexora(jev_response([]))
        tools, _ = make_tools([], reranker=make_reranker(handler))
        result = tools.search_knowledge("q", limit=10)
        assert result.knowledge == []
        assert handler.requests == []

    def test_cache_entries_keep_their_position(self):
        cached = [{
            "knowledge_id": "cached-1",
            "content": "q appears here",
            "metadata": {"category": "技術Tips", "tags": []},
            "project": "",
        }]
        handler = Lexora(jev_response([0.1 * i for i in range(10)] + [0.0, 0.0]))
        tools, _ = make_tools(
            IDS, reranker=make_reranker(handler, keep_k=8), memory=FakeMemory(cached)
        )
        result = tools.search_knowledge("q", limit=10)
        assert ids_of(result)[0] == "cached-1"
        assert ids_of(result)[1:] == ["k9", "k8", "k7", "k6", "k5", "k4", "k3", "k2"]
        # The cache entry was not sent to Lexora.
        state = json.loads(handler.requests[0]["state"])
        assert "q appears here" not in [c["text"] for c in state["candidates"]]


# --------------------------------------------------------------------------
# has_answer filtering (enabled per human decision B)
# --------------------------------------------------------------------------


class TestHasAnswer:
    def test_below_min_noul_returns_no_rag_candidates(self):
        handler = Lexora(jev_response([0.9] * 12, has_answer=0.2))
        tools, _ = make_tools(IDS, reranker=make_reranker(handler, min_noul=0.35))
        result = tools.search_knowledge("q", limit=10)
        assert result.success is True
        assert result.knowledge == []
        assert "該当なし" in result.message

    def test_at_min_noul_is_kept(self):
        handler = Lexora(jev_response([0.9] * 12, has_answer=0.35))
        tools, _ = make_tools(IDS, reranker=make_reranker(handler, min_noul=0.35))
        result = tools.search_knowledge("q", limit=10)
        assert len(result.knowledge) == 8

    def test_cache_entries_survive_no_match(self):
        cached = [{
            "knowledge_id": "cached-1",
            "content": "q appears here",
            "metadata": {"category": "技術Tips", "tags": []},
            "project": "",
        }]
        handler = Lexora(jev_response([0.9] * 12, has_answer=0.0))
        tools, _ = make_tools(IDS, reranker=make_reranker(handler), memory=FakeMemory(cached))
        result = tools.search_knowledge("q", limit=10)
        assert ids_of(result) == ["cached-1"]

    def test_null_provider_does_not_filter(self):
        handler = Lexora(jev_response([0.5] * 12, has_answer=0.0, provider="null"))
        tools, _ = make_tools(IDS, reranker=make_reranker(handler))
        result = tools.search_knowledge("q", limit=10)
        assert len(result.knowledge) == 10


# --------------------------------------------------------------------------
# D4: request shape and questions_hash stability
# --------------------------------------------------------------------------


class TestRequestShape:
    @pytest.mark.parametrize("n", [1, 12, 30, 40])
    def test_questions_fixed_regardless_of_n(self, n):
        handler = Lexora(jev_response([0.5] * min(n, 30)))
        reranker = make_reranker(handler)
        ids = [f"x{i}" for i in range(n)]
        reranker.rerank("what is X?", ids, text_of=lambda k: f"text {k}", id_of=lambda k: k)

        body = handler.requests[0]
        assert body["policy"] == "prismind.rerank"
        assert body["questions_version"] == "prismind.rerank/v1"
        expected_names = {question_name(i) for i in range(30)} | {HAS_ANSWER}
        assert set(body["questions"]) == expected_names
        assert all(q["type"] == "noul" for q in body["questions"].values())
        # The query is in state, never in a question.
        assert all("what is X?" not in q["instructions"] for q in body["questions"].values())
        state = json.loads(body["state"])
        assert state["query"] == "what is X?"
        assert [c["i"] for c in state["candidates"]] == list(range(30))
        for c in state["candidates"]:
            if c["i"] >= n:
                assert c["text"] == ""
            else:
                assert c["text"] == f"text x{c['i']}"
        assert len(body["state"]) <= 30 * 600 + 2000

    def test_questions_hash_constant_across_n_and_query(self):
        hashes = set()
        for n, query in [(1, "a"), (12, "b"), (30, "c"), (40, "d")]:
            handler = Lexora(jev_response([0.5] * min(n, 30)))
            reranker = make_reranker(handler)
            reranker.rerank(query, [f"x{i}" for i in range(n)],
                            text_of=lambda k: k, id_of=lambda k: k)
            hashes.add(lexora_questions_hash(handler.requests[0]["questions"]))
        assert len(hashes) == 1

    def test_candidate_text_truncated(self):
        handler = Lexora(jev_response([0.5]))
        reranker = make_reranker(handler, max_chars_per_candidate=10)
        reranker.rerank("q", ["a" * 50], text_of=lambda k: k, id_of=lambda k: "id")
        state = json.loads(handler.requests[0]["state"])
        assert state["candidates"][0]["text"] == "a" * 10

    def test_posts_to_lexora_decide_endpoint(self):
        urls = []

        def respond(request):
            urls.append(str(request.url))
            return jev_response([0.5])(request)

        reranker = make_reranker(respond, lexora_url="http://lexora:8110/")
        reranker.rerank("q", ["a"], text_of=lambda k: k, id_of=lambda k: k)
        assert urls == ["http://lexora:8110/v1/decide"]


# --------------------------------------------------------------------------
# D5: one evaluation log line per call
# --------------------------------------------------------------------------


class TestDecisionLog:
    def _records(self, caplog):
        return [
            json.loads(r.getMessage())
            for r in caplog.records
            if r.name == "spirrow_prismind.rerank.decision"
        ]

    def test_one_line_with_join_keys(self, caplog):
        caplog.set_level(logging.INFO, logger="spirrow_prismind.rerank.decision")
        handler = Lexora(jev_response([0.1, 0.9, 0.5]))
        reranker = make_reranker(handler)
        reranker.rerank("q", ["a", "b", "c"], text_of=lambda k: k, id_of=lambda k: k)

        records = self._records(caplog)
        assert len(records) == 1
        rec = records[0]
        assert rec["decision_id"] == "dec-123"
        assert rec["provider"] == "jev"
        assert rec["policy"] == "prismind.rerank"
        assert rec["questions_version"] == "prismind.rerank/v1"
        assert rec["n_candidates"] == 3
        assert rec["original_order"] == ["a", "b", "c"]
        assert rec["index_map"] == {"0": "a", "1": "b", "2": "c"}  # no padding slots
        assert rec["has_answer"] == 0.9
        assert rec["reranked"] is True
        assert rec["no_match"] is False
        assert rec["reranked_order"] == ["b", "c", "a"]

    def test_null_provider_logged_not_reranked(self, caplog):
        caplog.set_level(logging.INFO, logger="spirrow_prismind.rerank.decision")
        handler = Lexora(jev_response([0.5, 0.5], has_answer=0.5, provider="null"))
        make_reranker(handler).rerank("q", ["a", "b"], text_of=lambda k: k, id_of=lambda k: k)
        (rec,) = self._records(caplog)
        assert rec["decision_id"] == "dec-123"
        assert rec["provider"] == "null"
        assert rec["reranked"] is False

    def test_zero_candidates_logged_as_not_called(self, caplog):
        caplog.set_level(logging.INFO, logger="spirrow_prismind.rerank.decision")
        make_reranker(Lexora(jev_response([]))).rerank(
            "q", [], text_of=lambda k: k, id_of=lambda k: k
        )
        (rec,) = self._records(caplog)
        assert rec["called"] is False
        assert rec["n_candidates"] == 0

    def test_null_provider_without_answers_is_not_an_error(self, caplog):
        caplog.set_level(logging.INFO, logger="spirrow_prismind.rerank")
        handler = Lexora(lambda r: httpx.Response(
            200, json={"provider": "null", "decision_id": "dec-9", "latency_ms": 1}
        ))
        outcome = make_reranker(handler).rerank(
            "q", ["a", "b"], text_of=lambda k: k, id_of=lambda k: k
        )
        assert outcome.items == ["a", "b"]
        assert outcome.error is None
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        (rec,) = self._records(caplog)
        assert rec["decision_id"] == "dec-9"
        assert rec["provider"] == "null"
        assert rec["error"] is None
        assert rec["has_answer"] is None
        assert rec["reranked"] is False

    def test_jev_missing_answers_logs_error_with_decision_id(self, caplog):
        caplog.set_level(logging.INFO, logger="spirrow_prismind.rerank.decision")
        handler = Lexora(lambda r: httpx.Response(
            200, json={"provider": "jev", "decision_id": "dec-10", "latency_ms": 1}
        ))
        outcome = make_reranker(handler).rerank(
            "q", ["a", "b"], text_of=lambda k: k, id_of=lambda k: k
        )
        assert outcome.items == ["a", "b"]
        (rec,) = self._records(caplog)
        assert rec["decision_id"] == "dec-10"
        assert "answers" in rec["error"]

    def test_failure_logged_with_error(self, caplog):
        caplog.set_level(logging.INFO, logger="spirrow_prismind.rerank.decision")
        make_reranker(Lexora(_raise_connect)).rerank(
            "q", ["a"], text_of=lambda k: k, id_of=lambda k: k
        )
        (rec,) = self._records(caplog)
        assert rec["called"] is True
        assert rec["error"].startswith("ConnectError")
        assert rec["decision_id"] is None


# --------------------------------------------------------------------------
# D7: config validation at load time
# --------------------------------------------------------------------------


class TestConfig:
    def test_example_values_load(self):
        cfg = Config._from_dict({"rerank": {
            "enabled": True, "top_n": 30, "keep_k": 8,
            "max_chars_per_candidate": 600, "min_noul": 0.35,
        }}).rerank
        assert (cfg.enabled, cfg.top_n, cfg.keep_k, cfg.min_noul) == (True, 30, 8, 0.35)
        assert cfg.policy == "prismind.rerank"

    @pytest.mark.parametrize("section, fragment", [
        ({"top_n": 0}, "top_n"),
        ({"keep_k": 0}, "keep_k"),
        ({"top_n": 5, "keep_k": 6}, "keep_k"),
        ({"max_chars_per_candidate": 0}, "max_chars_per_candidate"),
        ({"top_n": 60, "max_chars_per_candidate": 600}, "state limit"),
        ({"min_noul": 1.5}, "min_noul"),
        ({"timeout_s": 0}, "timeout_s"),
        ({"policy": ""}, "policy"),
        ({"enabled": True, "lexora_url": ""}, "lexora_url"),
    ])
    def test_invalid_rejected_at_load(self, section, fragment):
        with pytest.raises(ValueError, match=fragment):
            Config._from_dict({"rerank": section})

    def test_load_from_file_rejects(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("[rerank]\ntop_n = 0\n", encoding="utf-8")
        with pytest.raises(ValueError):
            Config.load(str(p))


# --------------------------------------------------------------------------
# D8: no TypeSafe dependency
# --------------------------------------------------------------------------


def test_no_typesafe_dependency():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for name in ("pyproject.toml", "uv.lock"):
        text = (root / name).read_text(encoding="utf-8").lower()
        assert "typesafe" not in text, name
    for path in (root / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "import typesafe" not in text, path
        assert "from typesafe" not in text, path
