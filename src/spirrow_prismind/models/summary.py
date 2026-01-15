"""Summary sheet data models and templates."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# Summary sheet structure (key-value pairs in columns A and B)
SUMMARY_SHEET_TEMPLATE = [
    ["プロジェクト情報", ""],
    ["プロジェクト名", ""],
    ["説明", ""],
    ["開始日", ""],
    ["作成者", ""],
    ["", ""],
    ["進捗サマリ", ""],
    ["現在のフェーズ", "Phase 1"],
    ["完了タスク", "0"],
    ["全タスク", "1"],
    ["最終更新", ""],
]


def create_summary_template(
    project_name: str,
    description: str,
    created_by: str,
    start_date: Optional[datetime] = None,
) -> list[list[str]]:
    """Create initial summary sheet content.

    Args:
        project_name: Project display name
        description: Project description
        created_by: Creator name
        start_date: Project start date (defaults to now)

    Returns:
        2D list for writing to Google Sheets
    """
    if start_date is None:
        start_date = datetime.now()

    return [
        ["プロジェクト情報", ""],
        ["プロジェクト名", project_name],
        ["説明", description],
        ["開始日", start_date.strftime("%Y-%m-%d")],
        ["作成者", created_by],
        ["", ""],
        ["進捗サマリ", ""],
        ["現在のフェーズ", "Phase 1"],
        ["完了タスク", "0"],
        ["全タスク", "1"],
        ["最終更新", start_date.strftime("%Y-%m-%d %H:%M")],
    ]


# Initial progress data (Phase 1 with setup task)
INITIAL_PROGRESS_DATA = [
    ["Phase 1", "T01", "プロジェクト概要設定", "not_started", "", "", "プロジェクトの目標、スコープ、成果物を定義する"],
]


def create_progress_template() -> list[list[str]]:
    """Create initial progress sheet content with headers and initial task.

    Returns:
        2D list for writing to Google Sheets
    """
    from .progress import PROGRESS_SHEET_HEADERS

    return [
        PROGRESS_SHEET_HEADERS,
        *INITIAL_PROGRESS_DATA,
    ]


def create_catalog_template() -> list[list[str]]:
    """Create initial catalog sheet content with headers only.

    Returns:
        2D list for writing to Google Sheets
    """
    from .catalog import CATALOG_SHEET_HEADERS

    return [
        CATALOG_SHEET_HEADERS,
    ]


@dataclass
class ServiceStatus:
    """Status of a single service."""
    name: str
    available: bool
    url: str = ""
    message: str = ""
    # Detailed fields (populated when detailed=True)
    protocol: str = ""  # "rest" | "mcp"
    latency_ms: Optional[float] = None
    version: str = ""
    last_checked: str = ""


@dataclass
class CheckServicesResult:
    """Result of checking all services status."""
    success: bool
    services: list[ServiceStatus] = field(default_factory=list)
    all_required_available: bool = False
    message: str = ""
