"""Tests for FilesystemDocumentStore, against a real temporary filesystem."""

import os

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


def _case_sensitive(path) -> bool:
    """Whether `path`'s filesystem distinguishes `A` from `a`."""
    probe = path / "CaseProbe"
    probe.mkdir()
    try:
        return not (path / "caseprobe").exists()
    finally:
        probe.rmdir()


class TestDocsDirsOverride:
    """`[docs_dirs]` — a repository can keep documents in more than one place.

    Spirrow-VoxelWorld is why this exists: its specs live in `Docs/` while
    `docs/` holds only branching.md (which carries the ephemeral-develop
    sentinel). Both are live, and /srv/docs is case-sensitive, so a single
    lowercase guess finds one file out of fourteen.

    The mechanism under test is "several directories", not letter case, so
    these use distinct names. The real `Docs/` + `docs/` pairing is pinned
    separately below, where the filesystem allows it.
    """

    @pytest.fixture
    def multi_root(self, tmp_path):
        repo = tmp_path / "Spirrow-VoxelWorld"
        (repo / "Specs" / "percell-lod").mkdir(parents=True)
        (repo / "docs").mkdir(parents=True)
        (repo / "Specs" / "LOD_IMPLEMENTATION_SPEC.md").write_text(
            "---\nid: voxelworld:lod-implementation-spec\ntitle: LOD 実装仕様\n---\n\n本文\n",
            encoding="utf-8",
        )
        (repo / "Specs" / "percell-lod" / "spec.md").write_text(
            "# per-cell LOD\n", encoding="utf-8"
        )
        (repo / "docs" / "branching.md").write_text(
            "# branching\n\nEPHEMERAL-DEVELOP-PROCEDURE-V1\n", encoding="utf-8"
        )
        (tmp_path / "repos.toml").write_text(
            '[repos]\n'
            'spirrow-voxelworld = "Spirrow-VoxelWorld"\n'
            '\n'
            '[docs_dirs]\n'
            'spirrow-voxelworld = ["Specs", "docs"]\n',
            encoding="utf-8",
        )
        return tmp_path

    def test_scan_finds_every_configured_directory(self, multi_root):
        store = FilesystemDocumentStore(root=str(multi_root))

        ids = {d.doc_id for d in store.scan("spirrow-voxelworld")}

        assert ids == {
            "voxelworld:lod-implementation-spec",       # frontmatter id
            "spirrow-voxelworld:branching",             # provisional, from docs/
            "spirrow-voxelworld:percell-lod/spec",      # nested under Specs/
        }

    def test_without_the_override_only_docs_is_seen(self, multi_root):
        """The pre-fix behaviour, pinned: one file out of three."""
        (multi_root / "repos.toml").write_text(
            '[repos]\nspirrow-voxelworld = "Spirrow-VoxelWorld"\n',
            encoding="utf-8",
        )
        store = FilesystemDocumentStore(root=str(multi_root))

        assert [d.doc_id for d in store.scan("spirrow-voxelworld")] == [
            "spirrow-voxelworld:branching"
        ]

    def test_reads_by_id_across_directories(self, multi_root):
        store = FilesystemDocumentStore(root=str(multi_root))

        assert store.read("voxelworld:lod-implementation-spec").title == "LOD 実装仕様"
        assert "EPHEMERAL" in store.read("spirrow-voxelworld:branching").body

    def test_first_entry_is_where_writes_go(self, multi_root):
        store = FilesystemDocumentStore(
            root=str(multi_root), publisher=NullPublisher()
        )

        store.create(
            project_id="spirrow-voxelworld",
            folder_path="",
            name="New Spec",
            content="body",
        )

        assert (multi_root / "Spirrow-VoxelWorld/Specs/New-Spec.md").exists()
        assert not (multi_root / "Spirrow-VoxelWorld/docs/New-Spec.md").exists()

    def test_a_bare_string_is_accepted(self, multi_root):
        (multi_root / "repos.toml").write_text(
            '[repos]\nspirrow-voxelworld = "Spirrow-VoxelWorld"\n'
            '\n[docs_dirs]\nspirrow-voxelworld = "Specs"\n',
            encoding="utf-8",
        )
        store = FilesystemDocumentStore(root=str(multi_root))

        assert store.docs_dirs("spirrow-voxelworld") == ["Specs"]
        assert len(store.scan("spirrow-voxelworld")) == 2

    def test_default_is_lowercase_docs(self, root):
        assert FilesystemDocumentStore(root=str(root)).docs_dirs("spirrow-docs") == [
            "docs"
        ]

    def test_docs_and_Docs_side_by_side(self, tmp_path):
        """The actual VoxelWorld shape, where the filesystem allows it.

        Skipped on Windows/macOS default volumes, which fold case and cannot
        hold both directories. /srv/docs is ext4, where this is the real
        layout.
        """
        if not _case_sensitive(tmp_path):
            pytest.skip("filesystem folds case; cannot create Docs/ and docs/")

        repo = tmp_path / "Spirrow-VoxelWorld"
        (repo / "Docs").mkdir(parents=True)
        (repo / "docs").mkdir(parents=True)
        (repo / "Docs" / "spec.md").write_text(
            "---\nid: voxelworld:spec\n---\n\nspec\n", encoding="utf-8"
        )
        (repo / "docs" / "branching.md").write_text("# branching\n", encoding="utf-8")
        (tmp_path / "repos.toml").write_text(
            '[repos]\nspirrow-voxelworld = "Spirrow-VoxelWorld"\n'
            '\n[docs_dirs]\nspirrow-voxelworld = ["Docs", "docs"]\n',
            encoding="utf-8",
        )

        store = FilesystemDocumentStore(root=str(tmp_path))

        assert {d.doc_id for d in store.scan("spirrow-voxelworld")} == {
            "voxelworld:spec",
            "spirrow-voxelworld:branching",
        }


class TestReposConfigReload:
    """A repository added to repos.toml is picked up without a restart."""

    def test_new_repo_appears_without_restart(self, root):
        store = FilesystemDocumentStore(root=str(root))
        assert "extra-repo" not in store.repos

        extra = root / "extra-repo" / "docs"
        extra.mkdir(parents=True)
        (extra / "note.md").write_text(
            "---\nid: extra:note\ntitle: Note\n---\n\nbody\n", encoding="utf-8"
        )
        config = root / "repos.toml"
        config.write_text(
            config.read_text(encoding="utf-8") + 'extra-repo = "extra-repo"\n',
            encoding="utf-8",
        )
        # mtime resolution is coarse on some filesystems; make the edit visible
        stat = config.stat()
        os.utime(config, (stat.st_atime, stat.st_mtime + 10))

        assert "extra-repo" in store.repos
        assert [d.doc_id for d in store.scan("extra-repo")] == ["extra:note"]

    def test_unchanged_config_is_not_reloaded(self, root):
        store = FilesystemDocumentStore(root=str(root))
        first = store.repos

        assert store.repos is first
