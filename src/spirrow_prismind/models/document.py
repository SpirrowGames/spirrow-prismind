"""Document-related data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class DocumentType:
    """Custom document type definition."""

    type_id: str  # e.g., "meeting_notes"
    name: str  # e.g., "議事録"
    folder_name: str  # Folder name in Google Drive
    template_doc_id: str = ""  # Optional Google Docs template ID
    description: str = ""
    fields: list[str] = field(default_factory=list)  # Custom metadata fields
    is_builtin: bool = False  # True for default types (設計書, 実装手順書)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "type_id": self.type_id,
            "name": self.name,
            "folder_name": self.folder_name,
            "template_doc_id": self.template_doc_id,
            "description": self.description,
            "fields": self.fields,
            "is_builtin": self.is_builtin,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentType":
        """Create from dictionary."""
        return cls(
            type_id=data.get("type_id", ""),
            name=data.get("name", ""),
            folder_name=data.get("folder_name", ""),
            template_doc_id=data.get("template_doc_id", ""),
            description=data.get("description", ""),
            fields=data.get("fields", []),
            is_builtin=data.get("is_builtin", False),
        )


# Built-in document types
BUILTIN_DOCUMENT_TYPES = [
    DocumentType(
        type_id="design",
        name="設計書",
        folder_name="設計書",
        description="設計に関するドキュメント",
        is_builtin=True,
    ),
    DocumentType(
        type_id="procedure",
        name="実装手順書",
        folder_name="実装手順書",
        description="実装手順に関するドキュメント",
        is_builtin=True,
    ),
]


@dataclass
class ListDocumentTypesResult:
    """Result of listing document types."""

    success: bool
    document_types: list[DocumentType] = field(default_factory=list)
    message: str = ""


@dataclass
class RegisterDocumentTypeResult:
    """Result of registering a document type."""

    success: bool
    type_id: str = ""
    name: str = ""
    folder_created: bool = False
    message: str = ""


@dataclass
class DeleteDocumentTypeResult:
    """Result of deleting a document type."""

    success: bool
    type_id: str = ""
    message: str = ""


@dataclass
class DocReference:
    """Reference to a document in the catalog."""

    name: str
    doc_id: str
    reason: str = ""


@dataclass
class Document:
    """Full document content."""

    doc_id: str
    name: str
    doc_type: str  # 設計書/実装手順書/etc
    content: str
    source: str  # Google Docs / RAG
    metadata: dict = field(default_factory=dict)


@dataclass
class DocumentResult:
    """Result of getting a document."""

    found: bool
    document: Optional[Document] = None
    candidates: list[DocReference] = field(default_factory=list)
    message: str = ""


@dataclass
class CreateDocumentResult:
    """Result of creating a document."""

    success: bool
    doc_id: str = ""
    name: str = ""
    doc_url: str = ""
    source: str = ""
    catalog_registered: bool = False
    message: str = ""


@dataclass
class UpdateDocumentResult:
    """Result of updating a document."""

    success: bool
    doc_id: str = ""
    updated_fields: list[str] = field(default_factory=list)
    message: str = ""
