"""Tests for FilesystemDocumentStore, against a real temporary filesystem."""

import pytest

from spirrow_prismind.integrations.document_store import (
    DocumentNotFound,
    DocumentStoreError,
)
from spirrow_prismind.integrations.filesystem_document_store import (
    FilesystemDocumentStore,
    NullPublisher,
    parse_frontmatter,
    render_frontmatter,
)

DESIGN_DOC = """---
id: platform:docs-infrastructure-design
title: Spirrow ドキュメント基盤 設計書
product: platform
type: design
status: draft
keywords: [prismind, DocumentStore]
---

# 設計書

本文。
"""

NO_FRONTMATTER_DOC = """# Plain

frontmatter がない文書。
"""


@pytest.fixture
def root(tmp_path):
    """A /srv/docs lookalike with one repo and two documents."""
    docs = tmp_path / "spirrow-docs" / "docs"
    (docs / "platform").mkdir(parents=True)
    (docs / "platform" / "docs-infrastructure-design.md").write_text(
        DESIGN_DOC, encoding="utf-8"
    )
    (docs / "platform" / "plain.md").write_text(
        NO_FRONTMATTER_DOC, encoding="utf-8"
    )
    (tmp_path / "repos.toml").write_text(
        '[repos]\nspirrow-docs = "spirrow-docs"\n', encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def store(root):
    return FilesystemDocumentStore(
        root=str(root), publisher=NullPublisher(), user_name="test_user"
    )


@pytest.fixture
def read_only_store(root):
    return FilesystemDocumentStore(root=str(root), user_name="test_user")


class TestFrontmatter:
    def test_parse_splits_mapping_and_body(self):
        fm, body = parse_frontmatter(DESIGN_DOC)
        assert fm["id"] == "platform:docs-infrastructure-design"
        assert fm["keywords"] == ["prismind", "DocumentStore"]
        assert body.startswith("\n# 設計書")

    def test_parse_without_frontmatter_returns_text_unchanged(self):
        fm, body = parse_frontmatter(NO_FRONTMATTER_DOC)
        assert fm == {}
        assert body == NO_FRONTMATTER_DOC

    def test_malformed_frontmatter_is_ignored_not_fatal(self):
        text = "---\nid: [unclosed\n---\nbody\n"
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_non_mapping_frontmatter_is_ignored(self):
        text = "---\n- just\n- a list\n---\nbody\n"
        fm, _ = parse_frontmatter(text)
        assert fm == {}

    def test_round_trip(self):
        fm, body = parse_frontmatter(DESIGN_DOC)
        again_fm, again_body = parse_frontmatter(render_frontmatter(fm, body))
        assert again_fm == fm
        assert again_body == body

    def test_render_preserves_unicode(self):
        out = render_frontmatter({"title": "設計書"}, "body")
        assert "設計書" in out
        assert "\\u" not in out


class TestRead:
    def test_read_by_frontmatter_id(self, store):
        doc = store.read("platform:docs-infrastructure-design")

        assert doc.title == "Spirrow ドキュメント基盤 設計書"
        assert doc.mime_type == "text/markdown"
        assert doc.body.strip().startswith("# 設計書")
        assert doc.path == "spirrow-docs/docs/platform/docs-infrastructure-design.md"
        assert doc.frontmatter["product"] == "platform"

    def test_missing_id_gets_provisional_id(self, store):
        """No frontmatter 'id' -> '<product>:<relative slug>'."""
        doc = store.read("spirrow-docs:platform/plain")

        assert doc.title == "plain"
        assert doc.body.startswith("# Plain")

    def test_unknown_id_raises(self, store):
        with pytest.raises(DocumentNotFound):
            store.read("platform:nope")


class TestScan:
    def test_scan_returns_every_markdown_file(self, store):
        docs = store.scan("spirrow-docs")

        ids = {d.doc_id for d in docs}
        assert ids == {
            "platform:docs-infrastructure-design",
            "spirrow-docs:platform/plain",
        }

    def test_scan_carries_bodies_for_the_rag_index(self, store):
        """The catalog sync depends on scan() returning real bodies."""
        docs = {d.doc_id: d for d in store.scan("spirrow-docs")}

        assert "本文。" in docs["platform:docs-infrastructure-design"].body

    def test_scan_all_projects_when_none(self, store):
        assert len(store.scan(None)) == 2

    def test_unmapped_project_raises(self, store):
        with pytest.raises(DocumentStoreError):
            store.scan("unknown-project")


class TestWrites:
    def test_create_writes_file_with_frontmatter(self, store, root):
        doc = store.create(
            project_id="spirrow-docs",
            folder_path="conventions",
            name="Document Conventions",
            content="# 規約\n",
            frontmatter={"product": "platform", "type": "convention"},
        )

        path = root / "spirrow-docs/docs/conventions/Document-Conventions.md"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "# 規約" in text
        assert doc.frontmatter["title"] == "Document Conventions"
        # Readable straight back by the id it was given
        assert store.read(doc.doc_id).body.strip() == "# 規約"

    def test_create_refuses_to_clobber(self, store):
        store.create(
            project_id="spirrow-docs",
            folder_path="conventions",
            name="Dup",
            content="a",
        )
        with pytest.raises(DocumentStoreError):
            store.create(
                project_id="spirrow-docs",
                folder_path="conventions",
                name="Dup",
                content="b",
            )

    def test_write_replaces_body_and_keeps_frontmatter(self, store):
        store.write("platform:docs-infrastructure-design", "# 差し替え\n")

        doc = store.read("platform:docs-infrastructure-design")
        assert doc.body.strip() == "# 差し替え"
        assert doc.frontmatter["id"] == "platform:docs-infrastructure-design"
        assert doc.frontmatter["status"] == "draft"

    def test_write_append_concatenates(self, store):
        before = store.read("platform:docs-infrastructure-design").body
        store.write(
            "platform:docs-infrastructure-design", "追記\n", append=True
        )

        after = store.read("platform:docs-infrastructure-design").body
        assert after == before + "追記\n"

    def test_delete_archives_by_default(self, store, root):
        store.delete("platform:docs-infrastructure-design")

        path = root / "spirrow-docs/docs/platform/docs-infrastructure-design.md"
        assert path.exists()
        assert store.read(
            "platform:docs-infrastructure-design"
        ).frontmatter["status"] == "archived"

    def test_delete_permanent_unlinks(self, store, root):
        store.delete("platform:docs-infrastructure-design", permanent=True)

        path = root / "spirrow-docs/docs/platform/docs-infrastructure-design.md"
        assert not path.exists()

    def test_move_relocates_and_keeps_id(self, store, root):
        returned = store.move(
            "platform:docs-infrastructure-design",
            project_id="spirrow-docs",
            folder_path="archive",
        )

        assert returned == "platform:docs-infrastructure-design"
        assert (
            root / "spirrow-docs/docs/archive/docs-infrastructure-design.md"
        ).exists()
        assert not (
            root / "spirrow-docs/docs/platform/docs-infrastructure-design.md"
        ).exists()
        assert store.read("platform:docs-infrastructure-design") is not None

    def test_ensure_folder_reports_creation(self, store):
        assert store.ensure_folder(
            project_id="spirrow-docs", folder_path="brand-new"
        ) is True
        assert store.ensure_folder(
            project_id="spirrow-docs", folder_path="brand-new"
        ) is False


class TestReadOnlyWithoutPublisher:
    """No publisher -> no writes, so the sync clone never goes dirty."""

    def test_reads_still_work(self, read_only_store):
        assert read_only_store.read(
            "platform:docs-infrastructure-design"
        ).title
        assert len(read_only_store.scan("spirrow-docs")) == 2

    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.create(
                project_id="spirrow-docs",
                folder_path="x",
                name="n",
                content="c",
            ),
            lambda s: s.write("platform:docs-infrastructure-design", "c"),
            lambda s: s.delete("platform:docs-infrastructure-design"),
            lambda s: s.move(
                "platform:docs-infrastructure-design",
                project_id="spirrow-docs",
                folder_path="x",
            ),
        ],
        ids=["create", "write", "delete", "move"],
    )
    def test_writes_refuse(self, read_only_store, call):
        with pytest.raises(DocumentStoreError, match="read-only"):
            call(read_only_store)


class TestRepoResolution:
    def test_project_root_folder_id_selects_the_repo(self, root):
        """Design §6.2: root_folder_id carries a repo id in fs mode."""

        class StubProjectTools:
            def get_project_config(self, project=None, user=None):
                class Cfg:
                    project_id = project
                    root_folder_id = "spirrow-docs"

                return Cfg()

        store = FilesystemDocumentStore(
            root=str(root),
            project_tools=StubProjectTools(),
            publisher=NullPublisher(),
        )

        assert len(store.scan("spirrow-voxelworld")) == 2

    def test_missing_repos_toml_falls_back_to_directory_names(self, root):
        (root / "repos.toml").unlink()

        store = FilesystemDocumentStore(root=str(root))

        assert "spirrow-docs" in store.repos
        assert len(store.scan("spirrow-docs")) == 2
