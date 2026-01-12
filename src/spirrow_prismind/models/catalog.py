"""Catalog-related data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CatalogEntry:
    """Entry in the document catalog."""

    # Basic info (required)
    doc_id: str
    name: str
    source: str  # Google Docs / RAG
    doc_type: str  # 設計書/実装手順書/仕様書/規約/設定/パーソナル/その他

    # Project info (required)
    project: str
    phase_task: str  # P4-T01 / 共通 / 事前設計 / etc

    # Optional fields
    feature: str = ""
    reference_timing: str = ""  # 設計時/実装時/レビュー時/etc
    related_docs: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.now)
    created_by: str = ""
    status: str = "active"  # active / archived

    def to_sheet_row(self) -> list:
        """Convert to Google Sheets row format."""
        return [
            self.name,
            self.source,
            self.doc_id,
            self.doc_type,
            self.project,
            self.phase_task,
            self.feature,
            self.reference_timing,
            ",".join(self.related_docs),
            ",".join(self.keywords),
            self.updated_at.isoformat(),
            self.created_by,
            self.status,
        ]

    @classmethod
    def from_sheet_row(cls, row: list) -> "CatalogEntry":
        """Create from Google Sheets row."""
        # Handle missing columns gracefully
        def get(idx: int, default: str = "") -> str:
            return row[idx] if idx < len(row) else default

        updated_at = get(10)
        if updated_at:
            try:
                updated_at = datetime.fromisoformat(updated_at)
            except ValueError:
                updated_at = datetime.now()
        else:
            updated_at = datetime.now()

        return cls(
            name=get(0),
            source=get(1),
            doc_id=get(2),
            doc_type=get(3),
            project=get(4),
            phase_task=get(5),
            feature=get(6),
            reference_timing=get(7),
            related_docs=[x.strip() for x in get(8).split(",") if x.strip()],
            keywords=[x.strip() for x in get(9).split(",") if x.strip()],
            updated_at=updated_at,
            created_by=get(11),
            status=get(12, "active"),
        )

    def to_rag_document(self) -> dict:
        """Convert to RAG document format for indexing."""
        return {
            "id": f"catalog:{self.doc_id}",
            "content": f"{self.name} - {self.doc_type} - {self.project} - {self.phase_task}",
            "metadata": {
                "doc_id": self.doc_id,
                "name": self.name,
                "source": self.source,
                "doc_type": self.doc_type,
                "project": self.project,
                "phase_task": self.phase_task,
                "feature": self.feature,
                "reference_timing": self.reference_timing,
                "keywords": self.keywords,
                "status": self.status,
            },
        }


@dataclass
class SearchCatalogResult:
    """Result of searching the catalog."""

    success: bool
    total_count: int = 0
    documents: list[CatalogEntry] = field(default_factory=list)
    message: str = ""


@dataclass
class SyncCatalogResult:
    """Result of syncing the catalog."""

    success: bool
    synced_count: int = 0
    message: str = ""


# Column headers for the catalog sheet
CATALOG_SHEET_HEADERS = [
    "ドキュメント名",
    "保存先",
    "ID",
    "種別",
    "プロジェクト",
    "フェーズタスク",
    "フィーチャー",
    "参照タイミング",
    "関連ドキュメント",
    "キーワード",
    "更新日",
    "作成者",
    "ステータス",
]
