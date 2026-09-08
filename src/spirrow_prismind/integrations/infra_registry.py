"""Infra values as placeholders (spirrow-docs conventions §3.1 / §3.2).

Host names, tailnet addresses and server paths live in exactly one document --
``spirrow-docs/docs/platform/infra-registry.md`` -- and every other repository
writes ``{{PLACEHOLDER}}``. This module is what lets a caller stay unaware of
that: :meth:`Registry.resolve` fills placeholders in on the way out and
:meth:`Registry.substitute` takes real values back out on the way in.

The value table and the detection patterns are both read from the registry
document rather than declared here. There is a second implementation of the
same check -- the ``pre-commit`` hook in spirrow-docs, which cannot call this
one because Prismind is bound to localhost and unreachable from the loop host.
Two implementations with their own copies of the patterns would drift, so the
document owns them and both sides read it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Sections holding values to hide. Ports (§3) may appear literally -- once the
# host is a placeholder a port has nothing to point at -- and §4 is names
# already published in DNS.
SECRET_SECTIONS = ("1. ホスト", "2. サーバーパス")
PATTERN_SECTION = "5.1 検出パターン"

REGISTRY_RELATIVE = Path("spirrow-docs/docs/platform/infra-registry.md")

_ROW = re.compile(r"^\|\s*`\{\{(?P<name>[A-Z0-9_]+)\}\}`\s*\|\s*`(?P<value>[^`]+)`\s*\|")
_PATTERN_ROW = re.compile(r"^\|\s*`(?P<name>[^`]+)`\s*\|\s*`(?P<regex>.+?)`\s*\|")
_HEADING = re.compile(r"^#{2,3}\s+(?P<title>.+?)\s*$")


@dataclass(frozen=True)
class Finding:
    """One real value found where a placeholder belongs."""

    path: str
    line_no: int
    kind: str
    match: str
    line: str


@dataclass(frozen=True)
class Registry:
    values: dict[str, str] = field(default_factory=dict)
    patterns: tuple[tuple[str, re.Pattern[str]], ...] = ()

    @property
    def empty(self) -> bool:
        return not self.values

    def substitute(self, text: str) -> str:
        """Real value -> ``{{PLACEHOLDER}}``.

        Longest value first. ``/srv/docs`` is a prefix of ``/srv/docs-work``,
        and replacing the short one first would leave
        ``{{PATH_DOCS_CANONICAL}}-work`` in the document.
        """
        for name, value in sorted(self.values.items(), key=lambda kv: -len(kv[1])):
            text = text.replace(value, "{{" + name + "}}")
        return text

    def resolve(self, text: str) -> str:
        """``{{PLACEHOLDER}}`` -> real value."""
        for name, value in self.values.items():
            text = text.replace("{{" + name + "}}", value)
        return text

    def findings(self, text: str, path: str = "") -> list[Finding]:
        """Real values present in ``text`` that should have been placeholders."""
        found: list[Finding] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            for name, value in self.values.items():
                if value in line:
                    found.append(Finding(path, line_no, f"registered as {{{{{name}}}}}", value, line))
            for kind, pattern in self.patterns:
                for m in pattern.finditer(line):
                    if any(f.match == m.group(0) and f.line_no == line_no for f in found):
                        continue  # already named against its placeholder
                    found.append(Finding(path, line_no, kind, m.group(0), line))
        return found


def parse_registry(text: str) -> Registry:
    values: dict[str, str] = {}
    patterns: list[tuple[str, re.Pattern[str]]] = []
    section = ""
    for raw in text.splitlines():
        heading = _HEADING.match(raw)
        if heading:
            section = heading.group("title")
            continue
        if section in SECRET_SECTIONS:
            row = _ROW.match(raw)
            if row:
                values[row.group("name")] = row.group("value")
        elif section == PATTERN_SECTION:
            row = _PATTERN_ROW.match(raw)
            if row and row.group("name") != "名前":
                try:
                    # `|` is escaped in the markdown table so it does not split the row.
                    patterns.append(
                        (row.group("name"), re.compile(row.group("regex").replace(r"\|", "|")))
                    )
                except re.error:
                    logger.warning(
                        f"infra-registry: skipping unparsable pattern {row.group('name')!r}"
                    )
    return Registry(values, tuple(patterns))


def load_registry(path: Path) -> Registry:
    """Read the registry, or return an empty one if it is not usable.

    Reads fail open on purpose. The registry lives in a clone that a sync timer
    maintains, so it can be briefly missing or half-written; a document store
    that refused to serve anything in that window would be worse than one that
    hands back un-resolved placeholders. Writes and checks treat an empty
    registry as a hard error instead -- see the callers.
    """
    try:
        registry = parse_registry(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning(f"infra-registry: cannot read {path}: {exc}")
        return Registry()
    if registry.empty:
        logger.warning(f"infra-registry: no values parsed from {path}; has its format changed?")
    return registry


def registry_path_for(root: Path, override: Optional[str] = None) -> Path:
    return Path(override) if override else root / REGISTRY_RELATIVE
