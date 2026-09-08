"""Infra placeholders: the registry itself, and the store wired to it.

spirrow-docs conventions §3.1 / §3.2. The store's job is to make a caller
unaware of the convention -- real values on the way out, placeholders on the
way in -- while the scan-wide check still sees what is actually committed.
"""

import pytest

from spirrow_prismind.integrations.document_store import DocumentStoreError
from spirrow_prismind.integrations.filesystem_document_store import (
    FilesystemDocumentStore,
)
from spirrow_prismind.integrations.infra_registry import (
    load_registry,
    parse_registry,
)

REGISTRY_DOC = """\
---
id: platform:infra-registry
title: 台帳
---

# 台帳

## 1. ホスト

| プレースホルダ | 実値 | 役割 |
|---|---|---|
| `{{HOST_LOOP}}` | `sg-tomtebo-01` | loop host |
| `{{IP_LOOP}}` | `100.108.116.59` | tailnet IP |
| `{{HOST_LOOP_2}}` | （未配備） | not deployed |

## 2. サーバーパス

| プレースホルダ | 実値 |
|---|---|
| `{{PATH_DOCS_CANONICAL}}` | `/srv/docs` |
| `{{PATH_DOCS_WORK}}` | `/srv/docs-work` |

## 3. ポート

| ポート | サービス | host |
|---|---|---|
| 8117 | chatroom MCP | `{{HOST_SERVICES}}` |

## 5.1 検出パターン

| 名前 | 正規表現 | 説明 |
|---|---|---|
| `tailnet IP` | `\\b100\\.(?:6[4-9]\\|[7-9]\\d\\|1[01]\\d\\|12[0-7])\\.\\d{1,3}\\.\\d{1,3}\\b(?!/\\d)` | CGNAT |
| `host name` | `\\bsg-[a-z0-9]+-\\d+\\b` | sg-*-NN |
"""

DOC_WITH_PLACEHOLDERS = """\
---
id: mindwire:topology
title: topology
---

# topology

ループは `{{HOST_LOOP}}` で走り、chatroom は `{{HOST_SERVICES}}:8117`。
"""


@pytest.fixture
def registry():
    return parse_registry(REGISTRY_DOC)


# --- the registry document ----------------------------------------------


def test_ports_and_undeployed_rows_are_not_values(registry):
    assert registry.values == {
        "HOST_LOOP": "sg-tomtebo-01",
        "IP_LOOP": "100.108.116.59",
        "PATH_DOCS_CANONICAL": "/srv/docs",
        "PATH_DOCS_WORK": "/srv/docs-work",
    }


def test_patterns_are_read_from_the_document(registry):
    """The pre-commit hook has its own implementation; patterns in code drift."""
    assert [name for name, _ in registry.patterns] == ["tailnet IP", "host name"]


def test_substitute_prefers_the_longest_value(registry):
    """`/srv/docs` is a prefix of `/srv/docs-work`."""
    assert registry.substitute("/srv/docs-work と /srv/docs") == (
        "{{PATH_DOCS_WORK}} と {{PATH_DOCS_CANONICAL}}"
    )


def test_round_trip(registry):
    original = "sg-tomtebo-01 の /srv/docs-work（100.108.116.59）"
    assert registry.resolve(registry.substitute(original)) == original


def test_findings_name_the_placeholder_and_skip_ports(registry):
    assert registry.findings("`{{HOST_SERVICES}}:8117` へ") == []
    found = registry.findings("sg-tomtebo-01 へ")
    assert len(found) == 1 and "{{HOST_LOOP}}" in found[0].kind


def test_findings_catch_an_unregistered_value(registry):
    """A check that only knows registered values finds only what was remembered."""
    found = registry.findings("新 host sg-tomtebo-02")
    assert [f.kind for f in found] == ["host name"]


def test_an_unreadable_registry_fails_open(tmp_path):
    """The registry lives in a clone a timer maintains; refusing to serve any
    document while it is briefly missing would be worse than not resolving."""
    assert load_registry(tmp_path / "missing.md").empty


def test_an_unparsable_pattern_does_not_take_the_registry_down():
    broken = REGISTRY_DOC.replace(r"`\bsg-[a-z0-9]+-\d+\b`", "`[unclosed`")
    registry = parse_registry(broken)
    assert registry.values  # values still load
    assert [name for name, _ in registry.patterns] == ["tailnet IP"]


# --- the store ------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    """A /srv/docs lookalike: the registry's own repo plus a public one."""
    reg = tmp_path / "spirrow-docs" / "docs" / "platform"
    reg.mkdir(parents=True)
    (reg / "infra-registry.md").write_text(REGISTRY_DOC, encoding="utf-8")

    mw = tmp_path / "spirrow-mindwire" / "docs"
    mw.mkdir(parents=True)
    (mw / "topology.md").write_text(DOC_WITH_PLACEHOLDERS, encoding="utf-8")

    (tmp_path / "repos.toml").write_text(
        '[repos]\nspirrow-docs = "spirrow-docs"\nspirrow-mindwire = "spirrow-mindwire"\n',
        encoding="utf-8",
    )
    return FilesystemDocumentStore(
        root=str(tmp_path), work_root=str(tmp_path.parent / "work")
    )


def test_read_resolves_so_the_caller_never_sees_a_placeholder(store):
    doc = store.read("mindwire:topology")
    assert "sg-tomtebo-01" in doc.body
    assert "{{HOST_LOOP}}" not in doc.body


def test_scan_does_not_resolve(store):
    """The catalog and the §3.1 check must see what is committed. Resolving here
    would put real host names in the vector index and make every correct
    placeholder look like a violation."""
    doc = next(d for d in store.scan() if d.doc_id == "mindwire:topology")
    assert "{{HOST_LOOP}}" in doc.body
    assert "sg-tomtebo-01" not in doc.body


def test_write_takes_real_values_back_out(store):
    store.write("mindwire:topology", "ループは sg-tomtebo-01、work は /srv/docs-work。")
    written = (
        store.work_root / "spirrow-mindwire" / "docs" / "topology.md"
    ).read_text(encoding="utf-8")
    assert "sg-tomtebo-01" not in written
    assert "{{HOST_LOOP}}" in written and "{{PATH_DOCS_WORK}}" in written


def test_a_read_modify_write_cycle_does_not_change_the_document(store):
    before = store.read("mindwire:topology").body
    store.write("mindwire:topology", before)
    assert store.read("mindwire:topology").body == before


def test_create_stores_placeholders_and_returns_real_values(store):
    doc = store.create(
        project_id="spirrow-mindwire",
        folder_path="adr",
        name="host note",
        content="host は sg-tomtebo-01。",
    )
    assert "sg-tomtebo-01" in doc.body  # what the caller gets back
    on_disk = (
        store.work_root / "spirrow-mindwire" / "docs" / "adr" / "host-note.md"
    ).read_text(encoding="utf-8")
    assert "{{HOST_LOOP}}" in on_disk and "sg-tomtebo-01" not in on_disk


def test_spirrow_docs_keeps_its_real_values(store):
    """It is the collection point; substituting there would erase the table."""
    doc = store.create(
        project_id="spirrow-docs",
        folder_path="ops",
        name="runbook",
        content="host は sg-tomtebo-01。",
    )
    on_disk = (
        store.work_root / "spirrow-docs" / "docs" / "ops" / "runbook.md"
    ).read_text(encoding="utf-8")
    assert "sg-tomtebo-01" in on_disk
    assert "{{HOST_LOOP}}" not in on_disk
    assert doc.doc_id


def test_check_is_clean_when_every_document_uses_placeholders(store):
    assert store.check_placeholders() == []


def test_check_finds_a_value_committed_straight_to_git(store):
    """The path no store hook covers: a file edited in the clone and committed."""
    (store.root / "spirrow-mindwire" / "docs" / "deploy.md").write_text(
        "# deploy\n\nsg-tomtebo-01 から届かない\n", encoding="utf-8"
    )
    store._index_cache = None
    findings = store.check_placeholders()
    assert [f.match for f in findings] == ["sg-tomtebo-01"]
    assert findings[0].line_no == 3


def test_check_ignores_the_registry_repo(store):
    """spirrow-docs holds the values by definition."""
    assert all("spirrow-docs" not in f.path for f in store.check_placeholders())


def test_check_refuses_to_report_clean_without_a_registry(tmp_path):
    """A missing registry must never look like a passing check."""
    (tmp_path / "spirrow-mindwire" / "docs").mkdir(parents=True)
    (tmp_path / "repos.toml").write_text(
        '[repos]\nspirrow-mindwire = "spirrow-mindwire"\n', encoding="utf-8"
    )
    store = FilesystemDocumentStore(
        root=str(tmp_path), work_root=str(tmp_path.parent / "work")
    )
    with pytest.raises(DocumentStoreError, match="infra registry unusable"):
        store.check_placeholders()


def test_registry_is_reread_when_the_file_changes(store):
    assert "sg-tomtebo-01" in store.read("mindwire:topology").body
    path = store.infra_registry_path
    path.write_text(
        REGISTRY_DOC.replace("`sg-tomtebo-01`", "`sg-tomtebo-09`"), encoding="utf-8"
    )
    import os
    os.utime(path, (0, 0))  # force a different mtime
    assert "sg-tomtebo-09" in store.read("mindwire:topology").body
