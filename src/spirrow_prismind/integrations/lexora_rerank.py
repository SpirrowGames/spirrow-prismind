"""Re-rank search candidates with Lexora ``/v1/decide``.

Thread T-decide-rerank. msg-001 is the spec, msg-005 and msg-023 refine
the design, and the human's decision "B" (after msg-024) restored
msg-001's ``keep_k`` and ``has_answer`` filtering.

One request per search carries every candidate in ``state``. It asks
``answers_query_<i>`` (noul) for each slot and one ``has_answer`` (noul)
for the set as a whole.

Invariants this module keeps:

* The request always carries exactly ``top_n + 1`` questions, whatever
  the real candidate count N is. Slots ``k >= N`` are padded with
  ``text == ""`` and their answers are ignored. That keeps
  ``questions_hash`` constant for one ``questions_version`` (msg-007
  BLOCKING, resolved in msg-023 / msg-024).
* The query lives in ``state`` and never in a question's text. Questions
  depend only on ``top_n``, so the hash does not depend on the query.
* ``provider == "null"`` covers shadow, off and an active-mode fallback
  inside Lexora. Prismind has no answer to act on there, so it returns
  the original order with no truncation and no filtering (msg-005 A2/A3).
  The same holds for every transport or shape failure (msg-005 B6).
  Rerank never fails a search.
* Every call that reaches Lexora writes one structured log line. That
  line carries ``decision_id`` and the slot→knowledge_id map, which are
  the keys offline evaluation joins against Lexora's shadow rows
  (``shadow_of = decision_id``) (msg-005 A2, D5).

No TypeSafe SDK and no ``api.typesafe.ai``: this module talks only to the
Lexora URL in ``[rerank].lexora_url`` (msg-002).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence, TypeVar

import httpx

from ..config import RerankConfig

logger = logging.getLogger(__name__)

#: Separate logger name, so the per-call evaluation line can be routed or
#: filtered on its own.
decision_logger = logging.getLogger("spirrow_prismind.rerank.decision")

T = TypeVar("T")

HAS_ANSWER = "has_answer"

_ANSWERS_QUERY_INSTRUCTIONS = (
    "The state is JSON with a `query` and a list of `candidates`, each with "
    "an index `i` and a `text`. Does the text of the candidate whose `i` is "
    "{i} answer the query? A candidate whose text is empty does not answer "
    "the query."
)
_HAS_ANSWER_INSTRUCTIONS = (
    "The state is JSON with a `query` and a list of `candidates`, each with "
    "an index `i` and a `text`. Does at least one candidate answer the "
    "query? Candidates whose text is empty do not answer the query."
)


def question_name(i: int) -> str:
    """Name of the per-candidate question for slot ``i``."""
    return f"answers_query_{i}"


def build_questions(top_n: int) -> dict[str, dict[str, Any]]:
    """Return the fixed question set for ``top_n`` slots.

    Depends on ``top_n`` only, never on the query or on the real
    candidate count.
    """
    questions: dict[str, dict[str, Any]] = {
        question_name(i): {
            "type": "noul",
            "instructions": _ANSWERS_QUERY_INSTRUCTIONS.format(i=i),
        }
        for i in range(top_n)
    }
    questions[HAS_ANSWER] = {"type": "noul", "instructions": _HAS_ANSWER_INSTRUCTIONS}
    return questions


def build_state(query: str, texts: Sequence[str], top_n: int, max_chars: int) -> str:
    """Serialise the state: ``top_n`` slots, padded with ``""`` past N."""
    candidates = [
        {"i": k, "text": (texts[k][:max_chars] if k < len(texts) else "")}
        for k in range(top_n)
    ]
    return json.dumps(
        {"query": query, "candidates": candidates},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def rerank_order(
    scores: Sequence[float],
    has_answer: float,
    *,
    keep_k: int,
    min_noul: float,
) -> Optional[list[int]]:
    """The re-ranking rule, on slot indices only.

    ``scores[i]`` is the ``answers_query_<i>`` noul of scored slot ``i``;
    pass only the real slots (``i < min(N, top_n)``), never the padding.

    * ``has_answer < min_noul`` → ``None`` (「該当なし」: hand nothing on).
    * Otherwise the indices sorted by score, highest first, cut to
      ``keep_k``. The sort is stable, so ties keep search order.

    Shared by :meth:`LexoraReranker.rerank` and the offline evaluation
    (``scripts/eval_rerank.py``) so the two cannot drift apart
    (T-decide-rerank msg-066).
    """
    if has_answer < min_noul:
        return None
    return sorted(range(len(scores)), key=lambda i: -scores[i])[:keep_k]


@dataclass
class RerankOutcome:
    """What :meth:`LexoraReranker.rerank` did with one candidate list."""

    items: list  # the candidates to hand on, in final order
    called: bool = False  # an HTTP request was sent
    reranked: bool = False  # the order came from Lexora's answers
    no_match: bool = False  # has_answer < min_noul -> nothing handed on
    decision_id: Optional[str] = None
    provider: Optional[str] = None
    has_answer: Optional[float] = None
    error: Optional[str] = None
    log_record: dict[str, Any] = field(default_factory=dict)


class LexoraReranker:
    """Synchronous client that re-ranks one candidate list per call.

    ``search_knowledge`` is synchronous and runs outside the event loop
    (907e53b), so a blocking ``httpx.Client`` is the right tool
    (msg-005 B6).
    """

    def __init__(
        self,
        config: RerankConfig,
        http_client: Optional[httpx.Client] = None,
    ):
        errors = config.validation_errors()
        if errors:
            raise ValueError("Invalid [rerank] configuration: " + "; ".join(errors))
        self.config = config
        self._questions = build_questions(config.top_n)
        self._client = http_client or httpx.Client(timeout=config.timeout_s)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def build_request(self, query: str, texts: Sequence[str]) -> dict[str, Any]:
        """Return the ``POST /v1/decide`` body for the head of ``texts``."""
        cfg = self.config
        return {
            "state": build_state(query, texts[: cfg.top_n], cfg.top_n, cfg.max_chars_per_candidate),
            "questions": self._questions,
            "policy": cfg.policy,
            "questions_version": cfg.questions_version,
        }

    def close(self) -> None:
        self._client.close()

    def rerank(
        self,
        query: str,
        candidates: Sequence[T],
        text_of: Callable[[T], str],
        id_of: Callable[[T], str],
    ) -> RerankOutcome:
        """Re-rank ``candidates`` (already in search order).

        * N == 0: no request; the empty list comes back unchanged.
        * Any failure, or ``provider == "null"``: the original order,
          untruncated and unfiltered.
        * Otherwise: ``has_answer < min_noul`` → empty list (no match).
          Else the first ``top_n`` candidates sorted by their
          ``answers_query_<i>`` noul, descending (a stable sort, so ties
          keep search order), cut to ``keep_k``.

        Candidates past ``top_n`` are not scored. msg-023 appended them
        in search order, but ``keep_k <= top_n`` (validated) means they
        could never survive the ``keep_k`` cut once decision B restored
        ``keep_k``, so they are simply dropped on the re-ranked path.
        They still come back on every fallback path.
        """
        cfg = self.config
        original = list(candidates)
        n = len(original)
        head = original[: cfg.top_n]
        record: dict[str, Any] = {
            "event": "prismind.rerank",
            "policy": cfg.policy,
            "questions_version": cfg.questions_version,
            "n_candidates": n,
            "original_order": [id_of(c) for c in original],
            "index_map": {str(i): id_of(c) for i, c in enumerate(head)},
            "called": False,
            "decision_id": None,
            "provider": None,
            "has_answer": None,
            "reranked": False,
            "no_match": False,
            "error": None,
        }

        if n == 0:
            return self._finish(RerankOutcome(items=original), record)

        body = self.build_request(query, [text_of(c) for c in head])
        record["called"] = True
        outcome = RerankOutcome(items=original, called=True)
        try:
            response = self._client.post(
                cfg.lexora_url.rstrip("/") + "/v1/decide",
                json=body,
                timeout=cfg.timeout_s,
            )
            response.raise_for_status()
            payload = response.json()
            provider, decision_id = _parse_header(payload)
        except (httpx.HTTPError, ValueError) as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
            record["error"] = outcome.error
            logger.warning("rerank: Lexora /v1/decide failed, keeping search order: %s", outcome.error)
            return self._finish(outcome, record)

        outcome.provider = provider
        outcome.decision_id = decision_id
        record["provider"] = provider
        record["decision_id"] = decision_id

        if provider == "null":
            # shadow / off / active-mode fallback: no judgement to act on.
            # Decided on provider alone, before any answers are required:
            # whatever shape the answers take here is not an error. has_answer
            # is recorded only when it happens to be well-formed.
            try:
                outcome.has_answer = _noul(payload.get("answers") or {}, HAS_ANSWER)
                record["has_answer"] = outcome.has_answer
            except ValueError:
                pass
            return self._finish(outcome, record)

        # decision_id is already recorded, so a malformed answers object
        # still leaves the offline join key in the log line.
        try:
            answers = payload.get("answers")
            if not isinstance(answers, dict):
                raise ValueError("response has no answers object")
            has_answer = _noul(answers, HAS_ANSWER)
            scores = [_noul(answers, question_name(i)) for i in range(len(head))]
        except ValueError as exc:
            outcome.error = f"ValueError: {exc}"
            record["error"] = outcome.error
            logger.warning("rerank: unexpected /v1/decide answers, keeping search order: %s", exc)
            return self._finish(outcome, record)

        outcome.has_answer = has_answer
        record["has_answer"] = has_answer

        outcome.reranked = True
        record["reranked"] = True
        order = rerank_order(scores, has_answer, keep_k=cfg.keep_k, min_noul=cfg.min_noul)
        if order is None:
            outcome.no_match = True
            record["no_match"] = True
            outcome.items = []
            return self._finish(outcome, record)

        outcome.items = [head[i] for i in order]
        record["reranked_order"] = [id_of(c) for c in outcome.items]
        return self._finish(outcome, record)

    @staticmethod
    def _finish(outcome: RerankOutcome, record: dict[str, Any]) -> RerankOutcome:
        outcome.log_record = record
        decision_logger.info(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return outcome


def _parse_header(payload: Any) -> tuple[str, str]:
    """Return ``(provider, decision_id)``; answers are checked separately."""
    if not isinstance(payload, dict):
        raise ValueError("response body is not an object")
    provider = payload.get("provider")
    decision_id = payload.get("decision_id")
    if not isinstance(provider, str) or not provider:
        raise ValueError("response has no provider")
    if not isinstance(decision_id, str) or not decision_id:
        raise ValueError("response has no decision_id")
    return provider, decision_id


def _noul(answers: Any, name: str) -> float:
    if not isinstance(answers, dict):
        raise ValueError("answers is not an object")
    answer = answers.get(name)
    if not isinstance(answer, dict):
        raise ValueError(f"answer {name!r} missing")
    value = answer.get("noul")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"answer {name!r} has no numeric noul")
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"answer {name!r} noul {value} out of range")
    return value
