"""Tests for ``scripts/eval_rerank`` (T-decide-rerank PR2, msg-064 / msg-066).

No real HTTP: ``run-pairs`` talks to an ``httpx.MockTransport`` Lexora and a
fake RAG; ``score`` reads fixture files only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_rerank  # noqa: E402

from spirrow_prismind.config import RerankConfig
from spirrow_prismind.integrations.lexora_rerank import (
    HAS_ANSWER,
    LexoraReranker,
    question_name,
    rerank_order,
)
from spirrow_prismind.tools.knowledge_tools import KnowledgeTools
from tests.test_lexora_rerank import FakeRAG

CFG = RerankConfig(top_n=4, keep_k=2, min_noul=0.35)


def pair(qid, gold, query="q?", project="p"):
    return {"qid": qid, "query": query, "project": project, "gold_ids": gold}


def prismind_line(qid, ids, decision_id, top_n=4):
    head = ids[:top_n]
    return {
        "qid": qid,
        "event": "prismind.rerank",
        "decision_id": decision_id if ids else None,
        "n_candidates": len(ids),
        "original_order": list(ids),
        "index_map": {str(i): kid for i, kid in enumerate(head)},
        "called": bool(ids),
        "provider": "null" if ids else None,
    }


def answers(scores, has_answer=0.9, top_n=4):
    """answers_json; padding slots past len(scores) get 0.99 and must be ignored."""
    a = {question_name(i): {"noul": 0.99} for i in range(top_n)}
    for i, s in enumerate(scores):
        a[question_name(i)] = {"noul": s}
    a[HAS_ANSWER] = {"noul": has_answer}
    return json.dumps(a)


def null_row(decision_id, top_n=4):
    return {
        "decision_id": decision_id, "provider": "null", "provider_error": None,
        "answers_json": answers([0.5] * top_n, 0.5, top_n), "shadow_of": None,
    }


def shadow_row(of, scores, has_answer=0.9, error=None):
    return {
        "decision_id": f"s-{of}", "provider": "jev", "provider_error": error,
        "answers_json": "{}" if error else answers(scores, has_answer), "shadow_of": of,
    }


# --------------------------------------------------------------------------
# Shared rule
# --------------------------------------------------------------------------


class TestRerankOrder:
    def test_desc_stable_ties_and_keep_k(self):
        assert rerank_order([0.2, 0.9, 0.9, 0.5], 0.8, keep_k=3, min_noul=0.35) == [1, 2, 3]

    def test_below_min_noul_is_none(self):
        assert rerank_order([0.9], 0.34, keep_k=3, min_noul=0.35) is None

    def test_at_min_noul_is_kept(self):
        assert rerank_order([0.9], 0.35, keep_k=3, min_noul=0.35) == [0]

    def test_score_uses_the_production_function(self):
        assert eval_rerank.rerank_order is rerank_order


# --------------------------------------------------------------------------
# E1: pair validation
# --------------------------------------------------------------------------


class TestValidatePairs:
    def test_valid(self):
        lines = [json.dumps(pair("a", ["k1"])), "", json.dumps(pair("b", ["k2", "k3"], project=""))]
        pairs, errors = eval_rerank.validate_pairs(lines)
        assert errors == []
        assert [p["qid"] for p in pairs] == ["a", "b"]

    @pytest.mark.parametrize("obj, fragment", [
        ({"qid": "a", "query": "q", "project": "p"}, "missing"),
        ({**pair("a", ["k"]), "extra": 1}, "unknown keys"),
        (pair("", ["k"]), "qid"),
        (pair("a", ["k"], query=" "), "query"),
        ({**pair("a", ["k"]), "project": None}, "project"),
        (pair("a", []), "gold_ids"),
        (pair("a", ["k", "k"]), "gold_ids"),
        (pair("a", [""]), "gold_ids"),
    ])
    def test_rejects(self, obj, fragment):
        _, errors = eval_rerank.validate_pairs([json.dumps(obj)])
        assert len(errors) == 1 and fragment in errors[0]

    def test_rejects_non_json_and_duplicate_qid(self):
        lines = ["{nope", json.dumps(pair("a", ["k"])), json.dumps(pair("a", ["k"]))]
        _, errors = eval_rerank.validate_pairs(lines)
        assert "not JSON" in errors[0] and "duplicate qid" in errors[1]

    def test_min_pairs(self, tmp_path):
        f = tmp_path / "pairs.jsonl"
        f.write_text(json.dumps(pair("a", ["k"])) + "\n", encoding="utf-8")
        assert eval_rerank.main(["validate-pairs", "--pairs", str(f), "--min-pairs", "2"]) == 1
        assert eval_rerank.main(["validate-pairs", "--pairs", str(f), "--min-pairs", "1"]) == 0


# --------------------------------------------------------------------------
# run-pairs
# --------------------------------------------------------------------------


def _tools(ids, decision_id="dec-1", enabled=True, top_n=4, keep_k=2, requests=None):
    def respond(request):
        if requests is not None:
            requests.append(json.loads(request.content))
        body = {
            "answers": json.loads(answers([0.5] * top_n, 0.5, top_n)),
            "provider": "null", "decision_id": decision_id, "latency_ms": 1,
        }
        return httpx.Response(200, json=body)

    cfg = RerankConfig(enabled=enabled, lexora_url="http://lexora", top_n=top_n, keep_k=keep_k)
    reranker = LexoraReranker(cfg, http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    return KnowledgeTools(
        rag_client=FakeRAG(ids), project_tools=None, memory_client=None,
        user_name="u", reranker=reranker,
    )


class TestRunPairs:
    def test_writes_one_line_per_pair_with_qid(self, tmp_path, monkeypatch):
        ids = ["k0", "k1", "k2", "k3", "k4"]
        cfg = RerankConfig(enabled=True, lexora_url="http://lexora", top_n=4, keep_k=2)
        monkeypatch.setattr(eval_rerank, "_build_tools", lambda path: (_tools(ids), cfg))
        pairs_f = tmp_path / "pairs.jsonl"
        pairs_f.write_text(
            json.dumps(pair("a", ["k2"])) + "\n" + json.dumps(pair("b", ["k9"])) + "\n",
            encoding="utf-8",
        )
        out = tmp_path / "prismind.jsonl"
        assert eval_rerank.main(["run-pairs", "--pairs", str(pairs_f), "--out", str(out)]) == 0
        lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
        assert [x["qid"] for x in lines] == ["a", "b"]
        first = lines[0]
        assert first["decision_id"] == "dec-1"
        # search_knowledge fetches max(top_n, limit * 2) = 4 candidates
        assert first["n_candidates"] == 4
        assert first["original_order"] == ids[:4]
        assert first["index_map"] == {"0": "k0", "1": "k1", "2": "k2", "3": "k3"}

    @pytest.mark.parametrize("corpus, expected", [(40, 30), (12, 12)])
    def test_limit_keep_k_still_scores_the_full_top_n_pool(self, corpus, expected):
        # Einstein msg-072 objection 1 / Bohr msg-073: run-pairs searches with
        # limit = keep_k, yet the re-ranker must see min(corpus, top_n)
        # candidates, not keep_k (knowledge_tools: n_results = max(top_n, ...)).
        # A change that shrinks the pool to keep_k fails here.
        ids = [f"k{i}" for i in range(corpus)]
        requests: list[dict] = []
        tools = _tools(ids, top_n=30, keep_k=8, requests=requests)
        lines = eval_rerank.run_pairs([pair("a", ["k0"])], tools, keep_k=8)
        assert tools.rag.n_results_seen == [30]
        line = lines[0]
        assert line["n_candidates"] == expected
        assert len(line["index_map"]) == expected
        assert len(requests) == 1
        state = json.loads(requests[0]["state"])
        scored = [c for c in state["candidates"] if c["text"]]
        assert len(scored) == expected
        assert len(state["candidates"]) == 30  # padded to top_n, never keep_k

    def test_skipped_rerank_fails_loudly(self):
        # A disabled re-ranker logs nothing; run_pairs must not write a
        # file with silently missing lines.
        with pytest.raises(RuntimeError, match="expected one rerank log line"):
            eval_rerank.run_pairs([pair("a", ["k"])], _tools(["k0"], enabled=False), keep_k=2)


# --------------------------------------------------------------------------
# score
# --------------------------------------------------------------------------


def _score(pairs, prismind, lexora, cfg=CFG):
    return eval_rerank.score(pairs, prismind, lexora, cfg)


class TestJoinAndRebuild:
    def test_shadow_row_drives_the_rebuild(self):
        ids = ["k0", "k1", "k2", "k3"]
        r = _score(
            [pair("a", ["k2"])],
            [prismind_line("a", ids, "d1")],
            [null_row("d1"), shadow_row("d1", [0.1, 0.2, 0.9, 0.3])],
        )
        row = r["per_pair"][0]
        assert row["source"] == "shadow"
        assert row["after"] == ["k2", "k3"]  # keep_k = 2
        assert row["before"] == ["k0", "k1"]
        assert r["overall"]["before"]["top1"] == 0
        assert r["overall"]["after"]["top1"] == 1

    def test_ties_keep_search_order(self):
        ids = ["k0", "k1", "k2"]
        r = _score([pair("a", ["k1"])], [prismind_line("a", ids, "d1")],
                   [shadow_row("d1", [0.7, 0.7, 0.7])])
        assert r["per_pair"][0]["after"] == ["k0", "k1"]

    def test_padding_answers_ignored(self):
        # N=2 < top_n=4: slots 2,3 carry 0.99 and must not appear.
        r = _score([pair("a", ["k1"])], [prismind_line("a", ["k0", "k1"], "d1")],
                   [shadow_row("d1", [0.1, 0.2])])
        assert r["per_pair"][0]["after"] == ["k1", "k0"]

    def test_active_mode_answering_row(self):
        row = {**null_row("d1"), "provider": "jev", "answers_json": answers([0.1, 0.9, 0.2, 0.3])}
        r = _score([pair("a", ["k1"])], [prismind_line("a", ["k0", "k1", "k2", "k3"], "d1")], [row])
        assert r["per_pair"][0]["source"] == "answering"
        assert r["reranker"]["after"]["top1"] == 1

    def test_answers_json_from_sqlite_json_array(self, tmp_path):
        f = tmp_path / "lexora.json"
        f.write_text(json.dumps([shadow_row("d1", [0.9])]), encoding="utf-8")
        g = tmp_path / "lexora.jsonl"
        g.write_text(json.dumps(shadow_row("d1", [0.9])) + "\n", encoding="utf-8")
        assert eval_rerank.read_rows(f) == eval_rerank.read_rows(g)

    # msg-073 group (b): the evaluation data was not collected.
    @pytest.mark.parametrize("lexora, reason", [
        ([], "no_lexora_row"),
        ([null_row("d1")], "null_answer_only"),
    ])
    def test_not_collected_is_excluded_and_incomplete(self, lexora, reason):
        r = _score([pair("a", ["k0"])], [prismind_line("a", ["k0"], "d1")], lexora)
        assert r["evaluated"] == 0
        assert r["join"] == {"not_collected": 1, "by_reason": {reason: 1}}
        assert r["fallback"]["count"] == 0
        assert r["incomplete"].startswith("INCOMPLETE: re-extract Lexora log")

    def test_missing_prismind_line_is_not_collected(self):
        r = _score([pair("a", ["k0"])], [], [])
        assert r["evaluated"] == 0
        assert r["join"]["by_reason"] == {"no_prismind_line": 1}
        assert r["incomplete"] is not None

    # msg-073 group (a): production would have fallen back to search order.
    @pytest.mark.parametrize("decision_id, lexora, reason", [
        (None, [], "no_decision_id"),
        ("d1", [null_row("d1"), shadow_row("d1", [], error="jev:timeout")], "shadow_failed"),
        ("d1", [{**shadow_row("d1", [0.9]), "answers_json": json.dumps({HAS_ANSWER: {"noul": 0.9}})}],
         "bad_answers"),
    ])
    def test_fallback_is_scored_as_search_order_in_the_denominators(self, decision_id, lexora, reason):
        ids = ["k0", "k1", "k2", "k3", "k4"]
        line = {**prismind_line("a", ids, "d1"), "decision_id": decision_id}
        r = _score([pair("a", ["k1"])], [line], lexora)
        assert r["incomplete"] is None
        assert r["join"]["not_collected"] == 0
        assert r["evaluated"] == 1
        assert r["sources"]["fallback"] == 1
        assert r["fallback"] == {"count": 1, "rate": 1.0, "by_reason": {reason: 1}}
        row = r["per_pair"][0]
        assert row["fallback_reason"].startswith(reason)
        assert row["after"] == row["before"] == ["k0", "k1"]  # search order, not 該当なし
        assert not row["no_match"]
        # In every denominator, with after == before: no gain is credited.
        assert r["retrieval"] == {"gold_in_head": 1, "rate": 1.0}
        for block in ("reranker", "overall"):
            assert r[block]["n"] == 1
            assert r[block]["after"] == r[block]["before"]
            assert r[block]["after"]["topk"] == 1 and r[block]["after"]["top1"] == 0

    def test_fallback_dilutes_rather_than_disappears(self):
        # One real rerank lifting gold to top-1 plus one fallback: the rate is
        # 1/2, not the 1/1 that dropping the fallback would report.
        ids = ["k0", "k1", "k2", "k3"]
        r = _score(
            [pair("a", ["k2"]), pair("b", ["k2"])],
            [prismind_line("a", ids, "d1"), prismind_line("b", ids, "d2")],
            [shadow_row("d1", [0.1, 0.2, 0.9, 0.3]), shadow_row("d2", [], error="jev:timeout")],
        )
        assert r["overall"]["n"] == 2
        assert r["overall"]["after"]["top1_rate"] == 0.5
        assert r["fallback"]["rate"] == 0.5

    def test_zero_candidates_evaluated_without_lexora(self):
        r = _score([pair("a", ["k0"])], [prismind_line("a", [], None)], [])
        assert r["evaluated"] == 1 and r["join"]["not_collected"] == 0
        assert r["sources"]["no_candidates"] == 1
        assert r["retrieval"]["gold_in_head"] == 0
        assert r["no_match"]["count"] == 0


class TestMetrics:
    def _fixture(self):
        ids5 = ["k0", "k1", "k2", "k3", "k4"]
        pairs = [
            pair("hit", ["k2"]),       # gold in head, re-ranker lifts it to top-1
            pair("miss", ["k4"]),      # gold only past top_n: retrieval miss
            pair("nm_ok", ["k9"]),     # 該当なし, no gold anywhere: correct
            pair("nm_bad", ["k0"]),    # 該当なし, gold was scored: wrong
        ]
        prismind = [prismind_line(p["qid"], ids5, f"d-{p['qid']}") for p in pairs]
        lexora = [
            shadow_row("d-hit", [0.1, 0.2, 0.9, 0.3]),
            shadow_row("d-miss", [0.9, 0.1, 0.1, 0.1]),
            shadow_row("d-nm_ok", [0.1] * 4, has_answer=0.1),
            shadow_row("d-nm_bad", [0.9] * 4, has_answer=0.2),
        ]
        return _score(pairs, prismind, lexora)

    def test_retrieval_is_gold_in_head(self):
        r = self._fixture()
        assert r["evaluated"] == 4
        assert r["retrieval"] == {"gold_in_head": 2, "rate": 0.5}

    def test_reranker_block_only_counts_gold_in_head(self):
        r = self._fixture()["reranker"]
        assert r["n"] == 2
        # before: nm_bad has k0 at top-1; hit has k2 at rank 3 (outside K=2)
        assert r["before"] == {"top1": 1, "topk": 1, "top1_rate": 0.5, "topk_rate": 0.5}
        # after: hit → k2 top-1; nm_bad → 該当なし (miss)
        assert r["after"] == {"top1": 1, "topk": 1, "top1_rate": 0.5, "topk_rate": 0.5}

    def test_overall_block_counts_every_evaluated_pair(self):
        r = self._fixture()["overall"]
        assert r["n"] == 4
        assert r["before"]["top1"] == 1 and r["after"]["top1"] == 1
        assert r["after"]["top1_rate"] == 0.25

    def test_no_match_split_correct_and_wrong(self):
        r = self._fixture()["no_match"]
        assert (r["count"], r["correct"], r["wrong"]) == (2, 1, 1)
        assert r["wrong_rate"] == 0.25

    def test_empty_denominators_are_none(self):
        r = _score([], [], [])
        assert r["retrieval"]["rate"] is None
        assert r["reranker"]["after"]["top1_rate"] is None


def test_score_cli_end_to_end(tmp_path, capsys):
    ids = ["k0", "k1", "k2", "k3"]
    (tmp_path / "pairs.jsonl").write_text(json.dumps(pair("a", ["k2"])) + "\n", encoding="utf-8")
    (tmp_path / "p.jsonl").write_text(json.dumps(prismind_line("a", ids, "d1")) + "\n", encoding="utf-8")
    (tmp_path / "l.jsonl").write_text(
        json.dumps(null_row("d1", top_n=30)) + "\n" + json.dumps(shadow_row("d1", [0.1, 0.2, 0.9, 0.3])) + "\n",
        encoding="utf-8",
    )
    rc = eval_rerank.main([
        "score", "--pairs", str(tmp_path / "pairs.jsonl"),
        "--prismind-log", str(tmp_path / "p.jsonl"), "--lexora-log", str(tmp_path / "l.jsonl"),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    out = json.loads(captured.out)
    assert list(out)[:3] == ["incomplete", "join", "fallback"]
    assert out["incomplete"] is None
    assert out["config"] == {"top_n": 30, "keep_k": 8, "min_noul": 0.35}
    assert out["reranker"]["after"]["top1"] == 1
    assert out["reranker"]["before"]["top1"] == 0
    assert "per_pair" not in out


def test_score_cli_incomplete_warns_first_and_exits_nonzero(tmp_path, capsys):
    ids = ["k0", "k1"]
    nl = "\n"
    (tmp_path / "pairs.jsonl").write_text(
        json.dumps(pair("a", ["k1"])) + nl + json.dumps(pair("b", ["k1"])) + nl, encoding="utf-8"
    )
    (tmp_path / "p.jsonl").write_text(
        json.dumps(prismind_line("a", ids, "d1")) + nl + json.dumps(prismind_line("b", ids, "d2")) + nl,
        encoding="utf-8",
    )
    # The export missed d2's shadow row: only its null row came out.
    (tmp_path / "l.jsonl").write_text(
        json.dumps(shadow_row("d1", [0.1, 0.9])) + nl + json.dumps(null_row("d2")) + nl,
        encoding="utf-8",
    )
    rc = eval_rerank.main([
        "score", "--pairs", str(tmp_path / "pairs.jsonl"),
        "--prismind-log", str(tmp_path / "p.jsonl"), "--lexora-log", str(tmp_path / "l.jsonl"),
    ])
    assert rc == eval_rerank.EXIT_INCOMPLETE
    assert rc != 0
    captured = capsys.readouterr()
    assert captured.err.startswith("INCOMPLETE: re-extract Lexora log")
    out = json.loads(captured.out)
    assert list(out)[0] == "incomplete"
    assert out["incomplete"].startswith("INCOMPLETE: re-extract Lexora log (1 of 2")
    assert out["join"] == {"not_collected": 1, "by_reason": {"null_answer_only": 1}}
    assert out["evaluated"] == 1
