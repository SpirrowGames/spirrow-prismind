"""Offline evaluation of the Lexora ``/v1/decide`` search re-ranker.

Thread T-decide-rerank, PR2 (Bohr msg-064, revised in msg-066, cleared by
Einstein). It compares search order with re-ranked order on a set of
question → gold-document pairs, so that turning on ``[rerank].enabled``
can be decided on numbers.

Subcommands
-----------

``validate-pairs --pairs FILE [--min-pairs 40]``
    Check the pair file's schema (E1). One JSON object per line::

        {"qid": "q01", "query": "...", "project": "spirrow",
         "gold_ids": ["<knowledge_id>", ...]}

    A pair may have several gold documents; a hit is any of them.

``run-pairs --pairs FILE --out prismind_rerank.jsonl [--config config.toml]``
    Run ``search_knowledge`` in-process for each pair with the re-ranker on,
    and write the re-ranker's per-search log line (``decision_id``,
    ``n_candidates``, ``index_map``, ``original_order``, ...) plus the
    pair's ``qid``, one per line. The only remote endpoints touched are
    the RAG server and the Lexora ``/v1/decide`` URL from the config, the
    same path production takes. It never reads Lexora's decision log.
    The re-ranker runs regardless of ``[rerank].enabled``: the evaluation
    must not need production switched on. The memory cache is not used,
    so only RAG candidates are measured.

``score --pairs FILE --prismind-log prismind_rerank.jsonl --lexora-log lexora_decisions.jsonl``
    No network. Joins the two files on ``decision_id`` and prints the
    metrics as JSON. The Lexora file holds rows of Lexora's ``decisions``
    table (``lexora/decide/log.py``) as JSON objects — one per line, or a
    single JSON array (what ``sqlite3 -json`` prints). Only the columns
    ``decision_id``, ``provider``, ``provider_error``, ``answers_json`` and
    ``shadow_of`` are read.

How a pair is joined to Lexora's answers
----------------------------------------

While Lexora runs ``mode = "shadow"``, Prismind receives NullProvider
answers (noul 0.5 everywhere) and keeps search order. The real judgement
is the *shadow row* Lexora writes afterwards, whose ``shadow_of`` is the
``decision_id`` Prismind logged. So the join prefers a successful shadow
row; failing that, an answering row with the same ``decision_id`` whose
provider is not ``null`` (``mode = "active"``). Anything else counts as a
join failure, by reason. The re-ranked order is then rebuilt with
:func:`spirrow_prismind.integrations.lexora_rerank.rerank_order`, the
function production uses, so evaluation and production cannot drift.

Metrics (msg-066)
-----------------

* ``retrieval.gold_in_head`` — a gold document is among the candidates
  actually scored (slots ``0..min(N, top_n)-1``): recall@``top_n`` of the
  search step, not of the re-ranker.
* ``reranker`` — top-1 and top-K (K = ``keep_k``) hit, before and after,
  counted only over pairs with ``gold_in_head``.
* ``overall`` — the same over every evaluated pair (what the user sees).
* ``no_match`` — 「該当なし」 results, split into *correct* (no gold in
  the scored candidates) and *wrong* (a gold was there).
* ``join`` — pairs that could not be evaluated, by reason. Above zero,
  re-export Lexora's log once ingestion has caught up and score again.

Order of the real evaluation run (none of it is done by this PR)
---------------------------------------------------------------

1. ``run-pairs`` against the deployed RAG server and Lexora
   (``/v1/decide`` on Lexora's main and deployed, ``mode = "shadow"``).
2. By hand, export Lexora's decision rows for ``policy = 'prismind.rerank'``
   (both answering and shadow rows), e.g.
   ``sqlite3 -json decisions.db "SELECT * FROM decisions WHERE policy = 'prismind.rerank'" > lexora_decisions.json``.
3. ``score`` with the pair file and both logs.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

# Make the package importable when running from the repo root without install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spirrow_prismind.config import RerankConfig  # noqa: E402
from spirrow_prismind.integrations.lexora_rerank import (  # noqa: E402
    HAS_ANSWER,
    _noul,
    decision_logger,
    question_name,
    rerank_order,
)

PAIR_KEYS = {"qid", "query", "project", "gold_ids"}
DEFAULT_MIN_PAIRS = 40


# --------------------------------------------------------------------------
# E1: pair file
# --------------------------------------------------------------------------


def validate_pairs(lines: Iterable[str], min_pairs: int = 0) -> tuple[list[dict], list[str]]:
    """Parse and check pair lines. Returns ``(pairs, errors)``."""
    pairs: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        where = f"line {lineno}"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{where}: not JSON ({exc.msg})")
            continue
        if not isinstance(obj, dict):
            errors.append(f"{where}: not an object")
            continue
        missing = PAIR_KEYS - obj.keys()
        extra = obj.keys() - PAIR_KEYS
        if missing:
            errors.append(f"{where}: missing {sorted(missing)}")
        if extra:
            errors.append(f"{where}: unknown keys {sorted(extra)}")
        if missing or extra:
            continue
        qid, query, project, gold = obj["qid"], obj["query"], obj["project"], obj["gold_ids"]
        bad = False
        if not isinstance(qid, str) or not qid:
            errors.append(f"{where}: qid must be a non-empty string")
            bad = True
        elif qid in seen:
            errors.append(f"{where}: duplicate qid {qid!r}")
            bad = True
        if not isinstance(query, str) or not query.strip():
            errors.append(f"{where}: query must be a non-empty string")
            bad = True
        if not isinstance(project, str):
            errors.append(f"{where}: project must be a string")
            bad = True
        if (
            not isinstance(gold, list)
            or not gold
            or not all(isinstance(g, str) and g for g in gold)
            or len(set(gold)) != len(gold)
        ):
            errors.append(f"{where}: gold_ids must be a non-empty list of distinct non-empty strings")
            bad = True
        if bad:
            continue
        seen.add(qid)
        pairs.append(obj)
    if len(pairs) < min_pairs and not errors:
        errors.append(f"{len(pairs)} pairs, at least {min_pairs} required")
    return pairs, errors


def load_pairs(path: Path, min_pairs: int = 0) -> list[dict]:
    pairs, errors = validate_pairs(path.read_text(encoding="utf-8").splitlines(), min_pairs)
    if errors:
        raise ValueError(f"{path}: " + "; ".join(errors))
    return pairs


# --------------------------------------------------------------------------
# run-pairs
# --------------------------------------------------------------------------


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(json.loads(record.getMessage()))


def run_pairs(pairs: Sequence[dict], tools: Any, keep_k: int) -> list[dict]:
    """Search each pair; return one re-ranker log line per pair, with ``qid``.

    ``tools`` is a :class:`KnowledgeTools` whose re-ranker is enabled.
    The line is captured from the re-ranker's own decision logger, so it
    is exactly what production logs.
    """
    capture = _Capture()
    old_level = decision_logger.level
    decision_logger.addHandler(capture)
    decision_logger.setLevel(logging.INFO)
    out: list[dict] = []
    try:
        for pair in pairs:
            capture.records.clear()
            tools.search_knowledge(
                query=pair["query"],
                project=pair["project"],
                include_general=True,
                limit=keep_k,
            )
            if len(capture.records) != 1:
                raise RuntimeError(
                    f"qid {pair['qid']!r}: expected one rerank log line, got {len(capture.records)}"
                    " (is RAG reachable?)"
                )
            out.append({"qid": pair["qid"], **capture.records[0]})
    finally:
        decision_logger.removeHandler(capture)
        decision_logger.setLevel(old_level)
    return out


def _build_tools(config_path: Optional[str]):  # pragma: no cover - needs live services
    from spirrow_prismind.config import Config
    from spirrow_prismind.integrations import RAGClient
    from spirrow_prismind.integrations.lexora_rerank import LexoraReranker
    from spirrow_prismind.tools.knowledge_tools import KnowledgeTools

    config = Config.load(config_path)
    rerank_cfg = dataclasses.replace(config.rerank, enabled=True)
    rag = RAGClient(
        base_url=config.services.rag_server_url,
        collection_name=config.services.rag_collection,
    )
    tools = KnowledgeTools(
        rag_client=rag,
        project_tools=None,  # every pair names its project
        memory_client=None,  # RAG candidates only
        user_name=config.user_name,
        reranker=LexoraReranker(rerank_cfg),
    )
    return tools, rerank_cfg


# --------------------------------------------------------------------------
# score
# --------------------------------------------------------------------------


def read_rows(path: Path) -> list[dict]:
    """Read JSON Lines, or a single JSON array (``sqlite3 -json``)."""
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not all(isinstance(r, dict) for r in rows):
        raise ValueError(f"{path}: every row must be a JSON object")
    return rows


def _parse_answers(row: dict) -> Optional[dict]:
    raw = row.get("answers_json")
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        answers = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return answers if isinstance(answers, dict) else None


def lexora_answers_for(decision_id: str, rows_by_id: dict, shadows_by_of: dict) -> tuple[Optional[dict], str]:
    """Pick the Lexora answers for one Prismind ``decision_id``.

    Returns ``(answers, source)``. ``source`` is ``shadow`` or
    ``answering`` on success, otherwise the join-failure reason.
    """
    shadows = shadows_by_of.get(decision_id, [])
    for row in shadows:
        if row.get("provider_error") is None:
            answers = _parse_answers(row)
            if answers:
                return answers, "shadow"
    row = rows_by_id.get(decision_id)
    if row is not None and row.get("provider") != "null" and row.get("provider_error") is None:
        answers = _parse_answers(row)
        if answers:
            return answers, "answering"
    if shadows:
        return None, "shadow_failed"
    if row is None:
        return None, "no_lexora_row"
    return None, "null_answer_only"


def _hit(order: Optional[Sequence[str]], gold: set, k: int) -> bool:
    return bool(order) and any(kid in gold for kid in order[:k])


def score(pairs: Sequence[dict], prismind_rows: Sequence[dict], lexora_rows: Sequence[dict], cfg: RerankConfig) -> dict:
    """Compute the msg-066 metrics. Pure: no I/O."""
    by_qid = {r["qid"]: r for r in prismind_rows if "qid" in r}
    rows_by_id = {r["decision_id"]: r for r in lexora_rows if r.get("shadow_of") is None and r.get("decision_id")}
    shadows_by_of: dict[str, list[dict]] = {}
    for r in lexora_rows:
        if r.get("shadow_of"):
            shadows_by_of.setdefault(r["shadow_of"], []).append(r)

    k = cfg.keep_k
    unjoined: dict[str, int] = {}
    sources = {"shadow": 0, "answering": 0, "no_candidates": 0}
    evaluated = 0
    in_head = 0
    c = {name: 0 for name in (
        "rr_before_top1", "rr_before_topk", "rr_after_top1", "rr_after_topk",
        "all_before_top1", "all_before_topk", "all_after_top1", "all_after_topk",
        "no_match", "no_match_correct", "no_match_wrong",
    )}
    per_pair: list[dict] = []

    for pair in pairs:
        qid = pair["qid"]
        gold = set(pair["gold_ids"])
        rec = by_qid.get(qid)
        if rec is None:
            unjoined["no_prismind_line"] = unjoined.get("no_prismind_line", 0) + 1
            per_pair.append({"qid": qid, "joined": False, "reason": "no_prismind_line"})
            continue
        index_map = rec.get("index_map") or {}
        head = [index_map[str(i)] for i in range(len(index_map))]
        original = list(rec.get("original_order") or [])

        if rec.get("n_candidates", 0) == 0:
            source, after = "no_candidates", []
        else:
            decision_id = rec.get("decision_id")
            if not decision_id:
                unjoined["no_decision_id"] = unjoined.get("no_decision_id", 0) + 1
                per_pair.append({"qid": qid, "joined": False, "reason": "no_decision_id"})
                continue
            answers, source = lexora_answers_for(decision_id, rows_by_id, shadows_by_of)
            if answers is None:
                unjoined[source] = unjoined.get(source, 0) + 1
                per_pair.append({"qid": qid, "joined": False, "reason": source})
                continue
            try:
                has_answer = _noul(answers, HAS_ANSWER)
                scores = [_noul(answers, question_name(i)) for i in range(len(head))]
            except ValueError as exc:
                unjoined["bad_answers"] = unjoined.get("bad_answers", 0) + 1
                per_pair.append({"qid": qid, "joined": False, "reason": f"bad_answers: {exc}"})
                continue
            order = rerank_order(scores, has_answer, keep_k=k, min_noul=cfg.min_noul)
            after = None if order is None else [head[i] for i in order]

        sources[source] += 1
        evaluated += 1
        gih = any(kid in gold for kid in head)
        in_head += gih
        before_top1 = _hit(original, gold, 1)
        before_topk = _hit(original, gold, k)
        after_top1 = _hit(after, gold, 1)
        after_topk = _hit(after, gold, k)
        c["all_before_top1"] += before_top1
        c["all_before_topk"] += before_topk
        c["all_after_top1"] += after_top1
        c["all_after_topk"] += after_topk
        if gih:
            c["rr_before_top1"] += before_top1
            c["rr_before_topk"] += before_topk
            c["rr_after_top1"] += after_top1
            c["rr_after_topk"] += after_topk
        if after is None:
            c["no_match"] += 1
            c["no_match_wrong" if gih else "no_match_correct"] += 1
        per_pair.append({
            "qid": qid, "joined": True, "source": source, "gold_in_head": gih,
            "no_match": after is None, "before": original[:k], "after": after,
        })

    def rate(n: int, d: int) -> Optional[float]:
        return round(n / d, 4) if d else None

    def block(prefix: str, denom: int) -> dict:
        return {
            "n": denom,
            "before": {"top1": c[f"{prefix}_before_top1"], "topk": c[f"{prefix}_before_topk"],
                       "top1_rate": rate(c[f"{prefix}_before_top1"], denom),
                       "topk_rate": rate(c[f"{prefix}_before_topk"], denom)},
            "after": {"top1": c[f"{prefix}_after_top1"], "topk": c[f"{prefix}_after_topk"],
                      "top1_rate": rate(c[f"{prefix}_after_top1"], denom),
                      "topk_rate": rate(c[f"{prefix}_after_topk"], denom)},
        }

    return {
        "config": {"top_n": cfg.top_n, "keep_k": k, "min_noul": cfg.min_noul},
        "pairs": len(pairs),
        "evaluated": evaluated,
        "join": {"failed": sum(unjoined.values()), "by_reason": unjoined, "sources": sources},
        "retrieval": {"gold_in_head": in_head, "rate": rate(in_head, evaluated)},
        "reranker": block("rr", in_head),
        "overall": block("all", evaluated),
        "no_match": {
            "count": c["no_match"], "rate": rate(c["no_match"], evaluated),
            "correct": c["no_match_correct"], "correct_rate": rate(c["no_match_correct"], evaluated),
            "wrong": c["no_match_wrong"], "wrong_rate": rate(c["no_match_wrong"], evaluated),
        },
        "per_pair": per_pair,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _rerank_cfg(config_path: Optional[str]) -> RerankConfig:
    if config_path is None:
        return RerankConfig()
    from spirrow_prismind.config import Config

    return Config.load(config_path).rerank


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate-pairs", help="check the pair file schema")
    p.add_argument("--pairs", required=True, type=Path)
    p.add_argument("--min-pairs", type=int, default=DEFAULT_MIN_PAIRS)

    p = sub.add_parser("run-pairs", help="search every pair with the re-ranker on")
    p.add_argument("--pairs", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--config", default=None)

    p = sub.add_parser("score", help="join the logs offline and print metrics")
    p.add_argument("--pairs", required=True, type=Path)
    p.add_argument("--prismind-log", required=True, type=Path)
    p.add_argument("--lexora-log", required=True, type=Path)
    p.add_argument("--config", default=None, help="config.toml for [rerank]; defaults if omitted")
    p.add_argument("--per-pair", action="store_true", help="include the per-pair rows")

    args = parser.parse_args(argv)

    if args.cmd == "validate-pairs":
        pairs, errors = validate_pairs(
            args.pairs.read_text(encoding="utf-8").splitlines(), args.min_pairs
        )
        for e in errors:
            print(e, file=sys.stderr)
        print(f"{len(pairs)} valid pairs")
        return 1 if errors else 0

    if args.cmd == "run-pairs":
        pairs = load_pairs(args.pairs)
        tools, cfg = _build_tools(args.config)
        lines = run_pairs(pairs, tools, cfg.keep_k)
        args.out.write_text(
            "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in lines),
            encoding="utf-8",
        )
        print(f"wrote {len(lines)} lines to {args.out}")
        return 0

    pairs = load_pairs(args.pairs)
    result = score(pairs, read_rows(args.prismind_log), read_rows(args.lexora_log), _rerank_cfg(args.config))
    if not args.per_pair:
        result.pop("per_pair")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
