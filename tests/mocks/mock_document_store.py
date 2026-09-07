"""In-memory DocumentStore for tests.

Replaces the Google ``MagicMock`` triple (docs/drive/sheets) for everything
that goes through the document store seam. Tests that specifically exercise
Google or filesystem behaviour use the real classes instead --
``test_google_document_store.py`` and ``test_filesystem_document_store.py``.
"""

from typing import Any, Optional

from spirrow_prismind.integrations.document_store import (
    DocumentNotFound,
    DocumentStore,
    StoredDoc,
    slugify,
)


class MockDocumentStore(DocumentStore):
    """Dict-backed store that records what it was asked to do."""

    def __init__(self):
        self.docs: dict[str, StoredDoc] = {}
        self.folders: set[tuple[str, str]] = set()
        self.deleted: list[tuple[str, bool]] = []
        self.moves: list[tuple[str, str, str]] = []
        self.writes: list[tuple[str, str, bool]] = []
        self._counter = 0

    def _next_id(self, name: str) -> str:
        self._counter += 1
        return f"mock_{slugify(name)}_{self._counter}"

    def create(
        self,
        *,
        project_id: str,
        folder_path: str,
        name: str,
        content: str,
        frontmatter: Optional[dict[str, Any]] = None,
    ) -> StoredDoc:
        doc_id = self._next_id(name)
        doc = StoredDoc(
            doc_id=doc_id,
            title=name,
            body=content,
            url=f"mock://{project_id}/{folder_path}/{doc_id}",
            mime_type="text/markdown",
            path=f"{folder_path}/{doc_id}.md" if folder_path else f"{doc_id}.md",
            frontmatter=dict(frontmatter or {}),
        )
        self.docs[doc_id] = doc
        self.folders.add((project_id, folder_path))
        return doc

    def read(self, doc_id: str) -> StoredDoc:
        try:
            return self.docs[doc_id]
        except KeyError:
            raise DocumentNotFound(doc_id) from None

    def write(self, doc_id: str, content: str, *, append: bool = False) -> None:
        self.writes.append((doc_id, content, append))
        doc = self.docs.get(doc_id)
        if doc is None:
            # Tests often update a doc that only exists in the catalog.
            doc = StoredDoc(
                doc_id=doc_id,
                title=doc_id,
                body="",
                url=f"mock://{doc_id}",
                mime_type="text/markdown",
            )
            self.docs[doc_id] = doc
        doc.body = (doc.body + content) if append else content

    def move(self, doc_id: str, *, project_id: str, folder_path: str) -> str:
        self.moves.append((doc_id, project_id, folder_path))
        return doc_id

    def delete(self, doc_id: str, *, permanent: bool = False) -> None:
        self.deleted.append((doc_id, permanent))
        if permanent:
            self.docs.pop(doc_id, None)

    def scan(self, project_id: Optional[str] = None) -> list[StoredDoc]:
        return list(self.docs.values())

    def ensure_folder(self, *, project_id: str, folder_path: str) -> bool:
        key = (project_id, folder_path)
        if key in self.folders:
            return False
        self.folders.add(key)
        return True
