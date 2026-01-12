"""Document-related data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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
