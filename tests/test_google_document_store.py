"""Tests for GoogleDocumentStore.

The mimeType-branching tests came from ``test_document_tools.py``: that
behaviour is Google's, so it belongs to the Google store now that
``DocumentTools`` no longer knows what a mimeType is.
"""

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from spirrow_prismind.integrations.document_store import (
    DocumentNotFound,
    DocumentStoreError,
    UnsupportedDocumentFormat,
)
from spirrow_prismind.integrations.google_document_store import (
    NATIVE_DOC_MIME,
    GoogleDocumentStore,
)


@dataclass
class MockFileInfo:
    file_id: str
    name: str = ""
    mime_type: str = NATIVE_DOC_MIME
    parents: list = field(default_factory=list)
    web_view_link: str = ""


@dataclass
class MockDocContent:
    doc_id: str
    title: str
    body_text: str
    url: str


class StubProjectTools:
    """Minimal stand-in: project id -> root folder id."""

    def __init__(self, roots: dict):
        self.roots = roots

    def get_project_config(self, project=None, user=None):
        root = self.roots.get(project)
        if root is None:
            return None
        return MagicMock(project_id=project, root_folder_id=root)


@pytest.fixture
def drive():
    mock = MagicMock()
    mock.get_file_info.return_value = MockFileInfo(
        file_id="d", mime_type=NATIVE_DOC_MIME
    )
    return mock


@pytest.fixture
def docs():
    return MagicMock()


@pytest.fixture
def store(docs, drive):
    return GoogleDocumentStore(
        docs_client=docs,
        drive_client=drive,
        project_tools=StubProjectTools({"proj": "root_folder"}),
        user_name="test_user",
    )


class TestWrite:
    """mimeType branching, moved from TestUpdateDocumentNonNative."""

    def test_native_doc_replace_uses_docs_api(self, store, docs, drive):
        drive.get_file_info.return_value = MockFileInfo(
            file_id="native", mime_type=NATIVE_DOC_MIME
        )

        store.write("native", "new body", append=False)

        docs.replace_all_text.assert_called_once_with("native", "new body")
        drive.update_file_content.assert_not_called()

    def test_native_doc_append_uses_docs_api(self, store, docs, drive):
        drive.get_file_info.return_value = MockFileInfo(
            file_id="native", mime_type=NATIVE_DOC_MIME
        )

        store.write("native", "more", append=True)

        docs.append_text.assert_called_once_with("native", "more")

    def test_markdown_replace_uses_drive_media_upload(self, store, docs, drive):
        """text/markdown replace -> Drive media upload, not Docs API."""
        drive.get_file_info.return_value = MockFileInfo(
            file_id="md_doc", name="ADR-06", mime_type="text/markdown"
        )

        store.write("md_doc", "# ADR-06 v2.1\n\nfull body", append=False)

        docs.replace_all_text.assert_not_called()
        docs.append_text.assert_not_called()
        drive.update_file_content.assert_called_once_with(
            "md_doc", "# ADR-06 v2.1\n\nfull body", mime_type="text/markdown"
        )

    def test_markdown_append_downloads_and_concatenates(
        self, store, docs, drive
    ):
        """text/markdown append -> download existing + concat, then upload."""
        drive.get_file_info.return_value = MockFileInfo(
            file_id="md_ap_doc", name="notes", mime_type="text/markdown"
        )
        drive.download_file_content.return_value = b"existing\n"

        store.write("md_ap_doc", "appended", append=True)

        drive.download_file_content.assert_called_once_with("md_ap_doc")
        drive.update_file_content.assert_called_once_with(
            "md_ap_doc", "existing\nappended", mime_type="text/markdown"
        )
        docs.append_text.assert_not_called()

    def test_unsupported_native_type_fails_cleanly(self, store, docs, drive):
        """A native Sheet/Slide is rejected with no partial write."""
        drive.get_file_info.return_value = MockFileInfo(
            file_id="sheet_doc",
            name="data",
            mime_type="application/vnd.google-apps.spreadsheet",
        )

        with pytest.raises(UnsupportedDocumentFormat) as excinfo:
            store.write("sheet_doc", "should not be written", append=False)

        assert excinfo.value.mime_type == (
            "application/vnd.google-apps.spreadsheet"
        )
        docs.replace_all_text.assert_not_called()
        drive.update_file_content.assert_not_called()

    def test_unknown_mimetype_falls_back_to_docs_api(self, store, docs, drive):
        """If get_file_info fails, keep the pre-Phase-1 native-doc path."""
        drive.get_file_info.side_effect = RuntimeError("boom")

        store.write("mystery", "body", append=False)

        docs.replace_all_text.assert_called_once_with("mystery", "body")


class TestRead:
    def test_read_maps_document_content(self, store, docs):
        docs.get_document.return_value = MockDocContent(
            doc_id="doc1",
            title="Title",
            body_text="Body",
            url="https://docs.google.com/doc1",
        )

        stored = store.read("doc1")

        assert stored.doc_id == "doc1"
        assert stored.title == "Title"
        assert stored.body == "Body"
        assert stored.mime_type == NATIVE_DOC_MIME
        assert stored.path is None

    def test_read_missing_raises(self, store, docs):
        docs.get_document.side_effect = RuntimeError("404")

        with pytest.raises(DocumentNotFound):
            store.read("nope")


class TestCreate:
    def test_create_resolves_folder_then_writes_heading_and_body(
        self, store, docs, drive
    ):
        drive.ensure_folder_path.return_value = (
            MockFileInfo(file_id="design_folder"),
            False,
        )
        drive.create_document.return_value = MockFileInfo(
            file_id="new_doc",
            name="New Document",
            web_view_link="https://docs.google.com/document/d/new_doc/edit",
        )

        stored = store.create(
            project_id="proj",
            folder_path="設計書",
            name="New Document",
            content="Content here",
        )

        drive.ensure_folder_path.assert_called_once_with(
            path="設計書", parent_id="root_folder"
        )
        drive.create_document.assert_called_once_with(
            name="New Document", parent_id="design_folder"
        )
        assert stored.doc_id == "new_doc"
        assert stored.url.endswith("/new_doc/edit")
        # Heading, then the body after it
        assert docs.insert_text.call_count == 2

    def test_empty_folder_path_uses_project_root(self, store, drive):
        drive.create_document.return_value = MockFileInfo(file_id="d")

        store.create(
            project_id="proj",
            folder_path="",
            name="Doc",
            content="",
        )

        drive.ensure_folder_path.assert_not_called()
        drive.create_document.assert_called_once_with(
            name="Doc", parent_id="root_folder"
        )

    def test_folder_id_is_cached_across_calls(self, store, drive):
        """Second create for the same folder does not re-resolve it.

        This is the in-process replacement for the DocumentType.folder_ids
        cache that used to live in DocumentTools.
        """
        drive.ensure_folder_path.return_value = (
            MockFileInfo(file_id="f1"),
            False,
        )
        drive.create_document.return_value = MockFileInfo(file_id="d")

        store.create(
            project_id="proj", folder_path="設計書", name="A", content=""
        )
        store.create(
            project_id="proj", folder_path="設計書", name="B", content=""
        )

        assert drive.ensure_folder_path.call_count == 1


class TestMoveDeleteFolders:
    def test_move_resolves_target_and_moves(self, store, drive):
        drive.ensure_folder_path.return_value = (
            MockFileInfo(file_id="proc_folder"),
            False,
        )

        returned = store.move("doc1", project_id="proj", folder_path="実装手順書")

        drive.move_file.assert_called_once_with("doc1", "proc_folder")
        assert returned == "doc1"

    def test_delete_passes_permanent_through(self, store, drive):
        store.delete("doc1", permanent=True)
        drive.delete_file.assert_called_once_with("doc1", permanent=True)

        drive.delete_file.reset_mock()
        store.delete("doc2")
        drive.delete_file.assert_called_once_with("doc2", permanent=False)

    def test_ensure_folder_creates_only_when_absent(self, store, drive):
        drive.find_folder_by_name.return_value = None
        assert store.ensure_folder(project_id="proj", folder_path="新規") is True
        drive.create_folder.assert_called_once_with(
            name="新規", parent_id="root_folder"
        )

        drive.create_folder.reset_mock()
        drive.find_folder_by_name.return_value = MockFileInfo(file_id="exists")
        assert store.ensure_folder(project_id="proj", folder_path="既存") is False
        drive.create_folder.assert_not_called()

    def test_scan_is_not_supported(self, store):
        """Drive is not walked; the Google catalog syncs from Sheets."""
        with pytest.raises(DocumentStoreError):
            store.scan("proj")
