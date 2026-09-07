"""Tests for FilesystemDocumentStore, against a real temporary filesystem."""

import os
import time

import pytest

from spirrow_prismind.integrations.document_store import (
    DocumentNotFound,
    DocumentStoreError,
)
from spirrow_prismind.integrations.filesystem_document_store import (
    FilesystemDocumentStore,
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
        root=str(root), work_root=str(root / "_work"), user_name="test_user"
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
    """Writes land in the working tier, never in the canonical clone."""

    def test_create_writes_into_the_working_tier(self, store, root):
        doc = store.create(
            project_id="spirrow-docs",
            folder_path="conventions",
            name="Document Conventions",
            content="# 規約\n",
            frontmatter={"product": "platform", "type": "convention"},
        )

        working = (
            root / "_work/spirrow-docs/docs/conventions/Document-Conventions.md"
        )
        canonical = (
            root / "spirrow-docs/docs/conventions/Document-Conventions.md"
        )
        assert working.exists()
        assert not canonical.exists(), "the clone must stay clean"

        text = working.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "# 規約" in text
        assert doc.frontmatter["title"] == "Document Conventions"
        # Readable straight back, without the caller knowing which tier
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

    def test_editing_a_canonical_doc_copies_it_first(self, store, root):
        """Copy-on-write: the clone is untouched, the edit is in working."""
        canonical = (
            root / "spirrow-docs/docs/platform/docs-infrastructure-design.md"
        )
        before = canonical.read_text(encoding="utf-8")

        store.write("platform:docs-infrastructure-design", "# 差し替え\n")

        assert canonical.read_text(encoding="utf-8") == before
        working = (
            root
            / "_work/spirrow-docs/docs/platform/docs-infrastructure-design.md"
        )
        assert working.exists()

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

    def test_second_edit_stays_in_the_working_copy(self, store):
        store.write("platform:docs-infrastructure-design", "one\n")
        store.write("platform:docs-infrastructure-design", "two\n")

        assert store.read(
            "platform:docs-infrastructure-design"
        ).body.strip() == "two"

    def test_delete_archives_the_working_copy(self, store, root):
        store.write("platform:docs-infrastructure-design", "draft\n")

        store.delete("platform:docs-infrastructure-design")

        assert store.read(
            "platform:docs-infrastructure-design"
        ).frontmatter["status"] == "archived"
        assert (
            root / "spirrow-docs/docs/platform/docs-infrastructure-design.md"
        ).exists(), "canonical untouched"

    def test_delete_permanent_unlinks_the_working_copy_only(self, store, root):
        store.write("platform:docs-infrastructure-design", "draft\n")

        store.delete("platform:docs-infrastructure-design", permanent=True)

        assert not (
            root
            / "_work/spirrow-docs/docs/platform/docs-infrastructure-design.md"
        ).exists()
        # canonical is still there, so the id still resolves
        assert store.read("platform:docs-infrastructure-design") is not None

    def test_delete_refuses_on_a_canonical_only_document(self, store):
        with pytest.raises(DocumentStoreError, match="pull request"):
            store.delete("platform:docs-infrastructure-design")

    def test_move_refuses_on_a_canonical_only_document(self, store):
        with pytest.raises(DocumentStoreError, match="pull request"):
            store.move(
                "platform:docs-infrastructure-design",
                project_id="spirrow-docs",
                folder_path="archive",
            )

    def test_move_relocates_a_working_document(self, store, root):
        doc = store.create(
            project_id="spirrow-docs",
            folder_path="notes",
            name="Draft Note",
            content="body",
        )

        returned = store.move(
            doc.doc_id, project_id="spirrow-docs", folder_path="archive"
        )

        assert returned == doc.doc_id
        assert (root / "_work/spirrow-docs/docs/archive/Draft-Note.md").exists()
        assert not (
            root / "_work/spirrow-docs/docs/notes/Draft-Note.md"
        ).exists()

    def test_ensure_folder_reports_creation(self, store):
        assert store.ensure_folder(
            project_id="spirrow-docs", folder_path="brand-new"
        ) is True
        assert store.ensure_folder(
            project_id="spirrow-docs", folder_path="brand-new"
        ) is False


class TestTwoTierReads:
    """The caller never learns which tier answered."""

    def test_a_working_document_is_readable_and_scannable(self, store):
        doc = store.create(
            project_id="spirrow-docs",
            folder_path="notes",
            name="Working Note",
            content="draft body",
        )

        assert store.read(doc.doc_id).body.strip() == "draft body"
        assert doc.doc_id in {d.doc_id for d in store.scan("spirrow-docs")}

    def test_working_shadows_canonical_for_the_same_id(self, store):
        store.write("platform:docs-infrastructure-design", "newer\n")

        assert store.read(
            "platform:docs-infrastructure-design"
        ).body.strip() == "newer"
        ids = [d.doc_id for d in store.scan("spirrow-docs")]
        assert ids.count("platform:docs-infrastructure-design") == 1

    def test_scan_covers_both_tiers_without_duplicates(self, store):
        before = {d.doc_id for d in store.scan("spirrow-docs")}
        new = store.create(
            project_id="spirrow-docs",
            folder_path="notes",
            name="Extra",
            content="x",
        )

        after = {d.doc_id for d in store.scan("spirrow-docs")}
        assert after == before | {new.doc_id}


class TestReconcile:
    """Sync-time reconciliation (design 6.4.1)."""

    def _mirror_canonical_into_working(self, root):
        canonical = (
            root / "spirrow-docs/docs/platform/docs-infrastructure-design.md"
        )
        working = (
            root
            / "_work/spirrow-docs/docs/platform/docs-infrastructure-design.md"
        )
        working.parent.mkdir(parents=True, exist_ok=True)
        working.write_text(
            canonical.read_text(encoding="utf-8"), encoding="utf-8"
        )
        return working

    def test_a_promoted_document_is_removed_from_working(self, store, root):
        """Identical bodies mean the pull request landed."""
        working = self._mirror_canonical_into_working(root)

        entries = store.reconcile("spirrow-docs")

        promoted = [e for e in entries if e.state == "promoted"]
        assert [e.doc_id for e in promoted] == [
            "platform:docs-infrastructure-design"
        ]
        assert not working.exists()
        # still readable, from canonical now
        assert store.read("platform:docs-infrastructure-design") is not None

    def test_a_diverged_document_is_kept_and_reported(self, store, root):
        """An edit made after the pull request must not be deleted."""
        store.write("platform:docs-infrastructure-design", "edited after PR\n")
        working = (
            root
            / "_work/spirrow-docs/docs/platform/docs-infrastructure-design.md"
        )

        entries = store.reconcile("spirrow-docs")

        diverged = [e for e in entries if e.state == "diverged"]
        assert [e.doc_id for e in diverged] == [
            "platform:docs-infrastructure-design"
        ]
        assert working.exists(), "the edit must survive"
        assert store.read(
            "platform:docs-infrastructure-design"
        ).body.strip() == "edited after PR"

    def test_a_draft_not_yet_in_canonical_is_left_alone(self, store):
        doc = store.create(
            project_id="spirrow-docs",
            folder_path="notes",
            name="Still Drafting",
            content="wip",
        )

        entries = store.reconcile("spirrow-docs")

        drafts = [e for e in entries if e.state == "draft"]
        assert [e.doc_id for e in drafts] == [doc.doc_id]
        assert drafts[0].stale is False
        assert store.read(doc.doc_id) is not None

    def test_an_old_draft_is_flagged_stale(self, store, root):
        """The check ADR-2026-06-04-18 and -08-25-20 both needed."""
        doc = store.create(
            project_id="spirrow-docs",
            folder_path="notes",
            name="Stranded",
            content="wip",
        )
        path = root / "_work/spirrow-docs/docs/notes/Stranded.md"
        old = time.time() - 90 * 86400
        os.utime(path, (old, old))

        entries = store.reconcile("spirrow-docs")

        stranded = next(e for e in entries if e.doc_id == doc.doc_id)
        assert stranded.state == "draft"
        assert stranded.stale is True
        assert stranded.age_days > 89

    def test_remove_promoted_false_reports_without_deleting(self, store, root):
        working = self._mirror_canonical_into_working(root)

        entries = store.reconcile("spirrow-docs", remove_promoted=False)

        assert [e.state for e in entries] == ["promoted"]
        assert working.exists()

    def test_reconcile_is_quiet_when_nothing_is_in_working(self, store):
        assert store.reconcile("spirrow-docs") == []


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
        )

        assert len(store.scan("spirrow-voxelworld")) == 2

    def test_missing_repos_toml_falls_back_to_directory_names(self, root):
        (root / "repos.toml").unlink()

        store = FilesystemDocumentStore(root=str(root), work_root=str(root / "_work"))

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
        store = FilesystemDocumentStore(root=str(multi_root), work_root=str(multi_root / "_work"))

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
        store = FilesystemDocumentStore(root=str(multi_root), work_root=str(multi_root / "_work"))

        assert [d.doc_id for d in store.scan("spirrow-voxelworld")] == [
            "spirrow-voxelworld:branching"
        ]

    def test_reads_by_id_across_directories(self, multi_root):
        store = FilesystemDocumentStore(root=str(multi_root), work_root=str(multi_root / "_work"))

        assert store.read("voxelworld:lod-implementation-spec").title == "LOD 実装仕様"
        assert "EPHEMERAL" in store.read("spirrow-voxelworld:branching").body

    def test_first_entry_is_where_writes_go(self, multi_root):
        store = FilesystemDocumentStore(
            root=str(multi_root), work_root=str(multi_root / "_work")
        )

        store.create(
            project_id="spirrow-voxelworld",
            folder_path="",
            name="New Spec",
            content="body",
        )

        # The working tier mirrors the canonical layout, so promotion is a
        # straight copy back into the right docs_dir. It is named by the
        # repo id, not the clone directory -- "spirrow-voxelworld", not
        # "Spirrow-VoxelWorld". On a case-folding filesystem the two are
        # the same path, so assert the exact name.
        work_repo = multi_root / "_work" / "spirrow-voxelworld"
        assert [p.name for p in (multi_root / "_work").iterdir()] == [
            "spirrow-voxelworld"
        ]
        assert (work_repo / "Specs/New-Spec.md").exists()
        assert not (work_repo / "docs/New-Spec.md").exists()
        assert not (multi_root / "Spirrow-VoxelWorld/Specs/New-Spec.md").exists()

    def test_a_bare_string_is_accepted(self, multi_root):
        (multi_root / "repos.toml").write_text(
            '[repos]\nspirrow-voxelworld = "Spirrow-VoxelWorld"\n'
            '\n[docs_dirs]\nspirrow-voxelworld = "Specs"\n',
            encoding="utf-8",
        )
        store = FilesystemDocumentStore(root=str(multi_root), work_root=str(multi_root / "_work"))

        assert store.docs_dirs("spirrow-voxelworld") == ["Specs"]
        assert len(store.scan("spirrow-voxelworld")) == 2

    def test_default_is_lowercase_docs(self, root):
        assert FilesystemDocumentStore(root=str(root), work_root=str(root / "_work")).docs_dirs("spirrow-docs") == [
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

        store = FilesystemDocumentStore(root=str(tmp_path), work_root=str(tmp_path / "_work"))

        assert {d.doc_id for d in store.scan("spirrow-voxelworld")} == {
            "voxelworld:spec",
            "spirrow-voxelworld:branching",
        }


class TestReposConfigReload:
    """A repository added to repos.toml is picked up without a restart."""

    def test_new_repo_appears_without_restart(self, root):
        store = FilesystemDocumentStore(root=str(root), work_root=str(root / "_work"))
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
        store = FilesystemDocumentStore(root=str(root), work_root=str(root / "_work"))
        first = store.repos

        assert store.repos is first


class TestStaleIndexAfterExternalRemoval:
    """reconcile runs in another process; this one's cache goes stale.

    Found on sg-ai-server-01 while verifying the working tier. Every merged
    pull request hits it: reconcile removes the working copy, and this
    process keeps a cached path to a file that is gone. get_document then
    raised DocumentNotFound with the canonical file sitting right there,
    search_catalog went on listing the document, and nothing recovered it
    short of a restart.
    """

    def test_reads_fall_back_to_canonical_after_the_working_copy_vanishes(
        self, store, root
    ):
        doc_id = "platform:docs-infrastructure-design"
        store.write(doc_id, "edited\n")
        working = (
            root
            / "_work/spirrow-docs/docs/platform/docs-infrastructure-design.md"
        )
        assert store.read(doc_id).body.strip() == "edited"

        # What reconcile does, from a process that shares no cache with this
        # one -- so no invalidation reaches here.
        working.unlink()

        doc = store.read(doc_id)
        assert doc.body.strip().startswith("# 設計書")
        assert doc.path.startswith("spirrow-docs/")

    def test_a_document_removed_from_both_tiers_still_raises(self, store, root):
        doc_id = "platform:docs-infrastructure-design"
        assert store.read(doc_id) is not None

        (root / "spirrow-docs/docs/platform/docs-infrastructure-design.md").unlink()

        with pytest.raises(DocumentNotFound):
            store.read(doc_id)

    def test_write_after_an_external_removal_recovers(self, store, root):
        """The path the operator used to recover by hand."""
        doc_id = "platform:docs-infrastructure-design"
        store.write(doc_id, "first\n")
        (
            root
            / "_work/spirrow-docs/docs/platform/docs-infrastructure-design.md"
        ).unlink()

        store.write(doc_id, "second\n")

        assert store.read(doc_id).body.strip() == "second"
