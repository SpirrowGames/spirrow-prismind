"""Google Drive/Docs implementation of :class:`DocumentStore`.

This is the Drive/Docs code that used to sit inline in
``tools/document_tools.py``, moved behind the store seam without a change
of behaviour. It is the rollback path: with ``[documents] backend =
"google"`` Prismind must behave exactly as it did before Phase 1.

One deliberate difference from the old inline code is documented on
:meth:`GoogleDocumentStore._resolve_folder_id`.
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

from .document_store import (
    DocumentNotFound,
    DocumentStore,
    DocumentStoreError,
    StoredDoc,
    UnsupportedDocumentFormat,
)
from .google_docs import GoogleDocsClient
from .google_drive import GoogleDriveClient

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..tools.project_tools import ProjectTools

logger = logging.getLogger(__name__)

NATIVE_DOC_MIME = "application/vnd.google-apps.document"
NATIVE_MIME_PREFIX = "application/vnd.google-apps."


class GoogleDocumentStore(DocumentStore):
    """Documents stored as Google Docs / Drive files."""

    def __init__(
        self,
        docs_client: GoogleDocsClient,
        drive_client: GoogleDriveClient,
        project_tools: "ProjectTools",
        user_name: str = "default",
    ):
        """Initialize the Google-backed store.

        Args:
            docs_client: Google Docs client
            drive_client: Google Drive client
            project_tools: Used to resolve ``project_id`` to the project's
                Drive root folder. ``ProjectTools`` does not depend on
                documents, so this introduces no import cycle.
            user_name: Default user ID for project config lookups
        """
        self.docs = docs_client
        self.drive = drive_client
        self.project_tools = project_tools
        self.user_name = user_name
        # (project_id, folder_path) -> Drive folder id. See _resolve_folder_id.
        self._folder_id_cache: dict[tuple[str, str], str] = {}

    # ------------------------------------------------------------------
    # Folder resolution
    # ------------------------------------------------------------------

    def _project_root_folder_id(self, project_id: str) -> Optional[str]:
        config = self.project_tools.get_project_config(
            project=project_id, user=self.user_name
        )
        if not config:
            return None
        return config.root_folder_id

    def _resolve_folder_id(
        self, project_id: str, folder_path: str, *, create: bool = True
    ) -> Optional[str]:
        """Resolve a logical folder path to a Drive folder id.

        Before Phase 1 this cache lived on ``DocumentType.folder_ids`` and
        was persisted through ``_save_document_type``. A Drive folder id is
        a Google-only concept, so keeping it on the backend-neutral
        ``DocumentType`` model is exactly the coupling this seam removes;
        the cache now lives here and is per-process instead of persisted.

        The cost is one extra ``ensure_folder_path`` call per
        ``(project, folder_path)`` per server lifetime. That call is
        find-or-create, so the result is identical -- only a lookup is
        repeated. ``DocumentType.folder_ids`` is left in place so existing
        persisted data still loads.
        """
        key = (project_id, folder_path)
        cached = self._folder_id_cache.get(key)
        if cached:
            return cached

        root_folder_id = self._project_root_folder_id(project_id)
        if not folder_path:
            return root_folder_id
        if not root_folder_id:
            return None

        folder_info, created = self.drive.ensure_folder_path(
            path=folder_path,
            parent_id=root_folder_id,
        )
        if not folder_info:
            return root_folder_id
        if created:
            logger.info(
                f"Created folder path '{folder_path}' in project '{project_id}'"
            )
        self._folder_id_cache[key] = folder_info.file_id
        return folder_info.file_id

    # ------------------------------------------------------------------
    # DocumentStore
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        project_id: str,
        folder_path: str,
        name: str,
        content: str,
        frontmatter: Optional[dict[str, Any]] = None,
    ) -> StoredDoc:
        """Create a Google Doc and write its heading + body.

        ``frontmatter`` is ignored: a Google Doc has nowhere to put
        structured metadata. That metadata lives in the RAG/Sheets catalog
        on this backend, which Phase 1 does not touch.
        """
        target_folder_id = self._resolve_folder_id(project_id, folder_path)

        file_info = self.drive.create_document(
            name=name,
            parent_id=target_folder_id,
        )
        doc_id = file_info.file_id
        doc_url = (
            file_info.web_view_link
            or f"https://docs.google.com/document/d/{doc_id}/edit"
        )

        if content:
            # Heading first, styled HEADING_1, then the body after it.
            heading_text = name + "\n"
            self.docs.insert_text(doc_id, heading_text, index=1)
            self.docs.service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": 1,
                            "endIndex": 1 + len(heading_text),
                        },
                        "paragraphStyle": {"namedStyleType": "HEADING_1"},
                        "fields": "namedStyleType",
                    }
                }]},
            ).execute()
            self.docs.insert_text(doc_id, content, index=1 + len(heading_text))

        return StoredDoc(
            doc_id=doc_id,
            title=name,
            body=content,
            url=doc_url,
            mime_type=NATIVE_DOC_MIME,
            path=None,
            frontmatter={},
        )

    def read(self, doc_id: str) -> StoredDoc:
        try:
            doc_content = self.docs.get_document(doc_id)
        except Exception as e:
            raise DocumentNotFound(doc_id) from e

        return StoredDoc(
            doc_id=doc_id,
            title=doc_content.title,
            body=doc_content.body_text,
            url=doc_content.url,
            mime_type=NATIVE_DOC_MIME,
            path=None,
            frontmatter={},
        )

    def write(self, doc_id: str, content: str, *, append: bool = False) -> None:
        """Rewrite a document body, branching on its mimeType.

        Native Google Docs go through the Docs API (structured body).
        Non-native text files (text/markdown, text/plain, ...) are rejected
        by the Docs API with HTTP 400 and must be replaced via a Drive
        media upload, which keeps the same fileId.
        """
        try:
            file_mime = self.drive.get_file_info(doc_id).mime_type
        except Exception as e:
            # Could not determine mimeType -> fall back to the legacy Docs
            # API path, preserving prior behaviour for native docs.
            logger.warning(
                f"Could not determine mimeType for '{doc_id}', "
                f"assuming native Google Doc: {e}"
            )
            file_mime = NATIVE_DOC_MIME

        if file_mime == NATIVE_DOC_MIME:
            if append:
                self.docs.append_text(doc_id, content)
            else:
                self.docs.replace_all_text(doc_id, content)
            return

        if file_mime.startswith(NATIVE_MIME_PREFIX):
            # Another Google-native type (Sheets/Slides/...). Fail before
            # writing anything.
            raise UnsupportedDocumentFormat(doc_id, file_mime)

        # Non-native text file -> full byte replacement, doc_id kept.
        if append:
            try:
                existing_text = self.drive.download_file_content(doc_id).decode(
                    "utf-8"
                )
            except Exception as e:
                logger.warning(
                    f"Append download failed for '{doc_id}', "
                    f"treating existing content as empty: {e}"
                )
                existing_text = ""
            new_content = existing_text + content
        else:
            new_content = content

        self.drive.update_file_content(doc_id, new_content, mime_type=file_mime)

    def move(self, doc_id: str, *, project_id: str, folder_path: str) -> str:
        target_folder_id = self._resolve_folder_id(project_id, folder_path)
        if target_folder_id:
            self.drive.move_file(doc_id, target_folder_id)
            logger.info(f"Moved document '{doc_id}' to folder '{folder_path}'")
        return doc_id

    def delete(self, doc_id: str, *, permanent: bool = False) -> None:
        self.drive.delete_file(doc_id, permanent=permanent)

    def scan(self, project_id: Optional[str] = None) -> list[StoredDoc]:
        """Not supported on Drive.

        The Google catalog is rebuilt from the Sheets 目録, not by walking
        Drive -- see ``CatalogTools.sync_catalog``. Enumerating Drive would
        need a recursive listing per project and is not what any caller
        wants on this backend, so this raises rather than silently
        returning an empty list that would wipe the catalog.
        """
        raise DocumentStoreError(
            "GoogleDocumentStore.scan() is not supported; the Google catalog "
            "is synced from the Sheets 目録 (CatalogTools.sync_catalog)."
        )

    def ensure_folder(self, *, project_id: str, folder_path: str) -> bool:
        root_folder_id = self._project_root_folder_id(project_id)
        if not root_folder_id or not folder_path:
            return False

        existing_folder = self.drive.find_folder_by_name(
            name=folder_path,
            parent_id=root_folder_id,
        )
        if existing_folder:
            return False

        self.drive.create_folder(
            name=folder_path,
            parent_id=root_folder_id,
        )
        logger.info(
            f"Created folder '{folder_path}' in project '{project_id}'"
        )
        return True
