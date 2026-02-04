"""Knowledge-related data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class KnowledgeEntry:
    """A knowledge entry in RAG."""

    knowledge_id: str
    content: str
    category: str  # 問題解決/技術Tips/ベストプラクティス/落とし穴/etc
    project: Optional[str] = None  # None = generic knowledge
    tags: list[str] = field(default_factory=list)
    source: str = ""  # Where this knowledge came from
    created_at: datetime = field(default_factory=datetime.now)
    relevance_score: float = 0.0

    def to_rag_document(self) -> dict:
        """Convert to RAG document format for indexing."""
        return {
            "id": f"knowledge:{self.knowledge_id}",
            "content": self.content,
            "metadata": {
                "category": self.category,
                "project": self.project or "",
                "tags": self.tags,
                "source": self.source,
                "created_at": self.created_at.isoformat(),
            },
        }


@dataclass
class AddKnowledgeResult:
    """Result of adding knowledge."""

    success: bool
    knowledge_id: str = ""
    tags: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class SearchKnowledgeResult:
    """Result of searching knowledge."""

    success: bool
    total_count: int = 0
    knowledge: list[KnowledgeEntry] = field(default_factory=list)
    message: str = ""


@dataclass
class UpdateKnowledgeResult:
    """Result of updating knowledge."""

    success: bool
    knowledge_id: str = ""
    updated_fields: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class DeleteKnowledgeResult:
    """Result of deleting a knowledge entry."""

    success: bool
    knowledge_id: str = ""
    project: str = ""
    rag_deleted: bool = False
    cache_cleared: bool = False
    message: str = ""


# Knowledge categories
KNOWLEDGE_CATEGORIES = [
    "問題解決",
    "技術Tips",
    "ベストプラクティス",
    "落とし穴",
    "ワークアラウンド",
    "パフォーマンス",
    "その他",
]
