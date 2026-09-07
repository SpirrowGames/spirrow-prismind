"""Document storage backend interface.

Phase 1 of the Spirrow documentation infrastructure (see
``platform:docs-infrastructure-design`` §6.1) puts a seam between
``DocumentTools`` and the place documents physically live, so the backend
can move from Google Drive/Docs to a Git-synced filesystem on
sg-ai-server-01 without touching the catalog, Sheets, or RAG paths.

Two implementations sit behind this interface:

- :class:`~.google_document_store.GoogleDocumentStore` -- the existing
  Drive/Docs behaviour, moved here unchanged. This is the rollback path.
- :class:`~.filesystem_document_store.FilesystemDocumentStore` -- Markdown
  files with YAML frontmatter under ``/srv/docs/<repo>/docs/...``.

The style follows ``MemoryBackend`` in :mod:`.memory_client`: an ABC with
``@abstractmethod``, not a ``typing.Protocol``. The design sketch wrote
``Protocol``/``BaseModel``; the codebase has no pydantic models and uses
ABCs for its one existing backend seam, so the handoff brief's "same
style as MemoryBackend" wins over the sketch's pseudo-code.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "DocumentStore",
    "DocumentStoreError",
    "DocumentNotFound",
    "UnsupportedDocumentFormat",
    "StoredDoc",
    "slugify",
]


class DocumentStoreError(Exception):
    """Base class for document store failures."""


class DocumentNotFound(DocumentStoreError):
    """No document exists for the given ``doc_id``."""

    def __init__(self, doc_id: str):
        self.doc_id = doc_id
        super().__init__(f"Document not found: {doc_id}")


class UnsupportedDocumentFormat(DocumentStoreError):
    """The stored document is not text this store can rewrite.

    Raised instead of performing a partial write. ``GoogleDocumentStore``
    raises it for Google-native non-Doc types (Sheets, Slides, ...), which
    the Docs API rejects with HTTP 400. Callers turn it into a user-facing
    message; the important property is that nothing was written.
    """

    def __init__(self, doc_id: str, mime_type: str):
        self.doc_id = doc_id
        self.mime_type = mime_type
        super().__init__(
            f"Document '{doc_id}' has unsupported mimeType '{mime_type}'"
        )


@dataclass
class StoredDoc:
    """A document as the backing store sees it.

    ``doc_id`` is the store's own identifier: a Drive fileId for
    ``GoogleDocumentStore``, a frontmatter ``id`` (e.g.
    ``platform:docs-infrastructure-design``) for the filesystem store.
    Callers treat it as opaque.
    """

    doc_id: str
    title: str
    body: str
    url: str
    mime_type: str
    path: Optional[str] = None  # filesystem store only; None for Google
    frontmatter: dict[str, Any] = field(default_factory=dict)


_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_SPACES = re.compile(r"[\s_]+", re.UNICODE)


def slugify(name: str) -> str:
    """Turn a document name into a filesystem-safe slug.

    Unicode word characters are kept, so Japanese titles survive intact
    (``"設計書 v0.1"`` -> ``"設計書-v01"``) rather than collapsing to an
    empty string the way an ASCII-only slugifier would.
    """
    slug = _SLUG_STRIP.sub("", name).strip()
    slug = _SLUG_SPACES.sub("-", slug)
    slug = slug.strip("-")
    return slug or "untitled"


class DocumentStore(ABC):
    """Where document bodies are created, read, written, moved, deleted.

    Deliberately *not* in scope (these stay on their current path in
    Phase 1 and move in Phase 1.5): the RAG catalog, the Sheets catalog,
    ``list_documents``, ``search_catalog``, progress/session/knowledge
    tools, and project setup.
    """

    @abstractmethod
    def create(
        self,
        *,
        project_id: str,
        folder_path: str,
        name: str,
        content: str,
        frontmatter: Optional[dict[str, Any]] = None,
    ) -> StoredDoc:
        """Create a document and return it.

        Args:
            project_id: Project identifier. The store resolves this to its
                own container (Drive root folder / repository directory).
            folder_path: Slash-separated logical folder, e.g.
                ``"設計/詳細設計"``. Empty means the project root.
            name: Human-readable document name.
            content: Body text. May be empty.
            frontmatter: Structured metadata. Stores that have nowhere to
                put it (Google) ignore it.

        Raises:
            DocumentStoreError: creation failed; nothing was left behind.
        """
        ...

    @abstractmethod
    def read(self, doc_id: str) -> StoredDoc:
        """Fetch a document by id.

        Raises:
            DocumentNotFound: no such document.
        """
        ...

    @abstractmethod
    def write(self, doc_id: str, content: str, *, append: bool = False) -> None:
        """Replace (or append to) a document's body, keeping its id.

        Raises:
            DocumentNotFound: no such document.
            UnsupportedDocumentFormat: the document is not rewritable text.
                Nothing was written.
        """
        ...

    @abstractmethod
    def move(self, doc_id: str, *, project_id: str, folder_path: str) -> str:
        """Move a document to another logical folder.

        Returns:
            The document id after the move. Both current backends keep the
            id stable, but callers should use the returned value.
        """
        ...

    @abstractmethod
    def delete(self, doc_id: str, *, permanent: bool = False) -> None:
        """Delete a document.

        The default is the store's reversible delete (Drive trash /
        ``status: archived`` frontmatter). ``permanent=True`` destroys it.
        """
        ...

    @abstractmethod
    def scan(self, project_id: Optional[str] = None) -> list[StoredDoc]:
        """Enumerate documents, for rebuilding the catalog.

        Args:
            project_id: Restrict to one project; ``None`` means every
                project the store knows about.
        """
        ...

    @abstractmethod
    def ensure_folder(self, *, project_id: str, folder_path: str) -> bool:
        """Make sure a logical folder exists.

        Returns:
            True if this call created it, False if it already existed.
        """
        ...
