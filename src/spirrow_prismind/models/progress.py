"""Progress-related data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TaskProgress:
    """Progress of a single task."""

    task_id: str  # e.g., "T01"
    name: str  # e.g., "BTノード生成"
    status: str  # not_started / in_progress / completed / blocked
    blockers: list[str] = field(default_factory=list)
    completed_at: Optional[datetime] = None
    notes: str = ""
    # Extended fields (v2)
    priority: str = "medium"  # high / medium / low
    category: str = ""  # bug / feature / refactor / design / test etc.
    blocked_by: list[str] = field(default_factory=list)  # e.g., ["T01", "T02"]


@dataclass
class PhaseProgress:
    """Progress of a phase."""

    phase: str  # e.g., "Phase 4"
    status: str  # not_started / in_progress / completed
    tasks: list[TaskProgress] = field(default_factory=list)


@dataclass
class GetProgressResult:
    """Result of getting progress."""

    success: bool
    project: str = ""
    current_phase: str = ""
    phases: list[PhaseProgress] = field(default_factory=list)
    message: str = ""


@dataclass
class TaskDefinition:
    """Definition for creating a new task."""

    phase: str  # e.g., "Phase 4"
    task_id: str  # e.g., "T02"
    name: str  # e.g., "BTノード接続"
    description: str = ""


@dataclass
class UpdateProgressResult:
    """Result of updating progress."""

    success: bool
    project: str = ""
    task_id: str = ""
    updated_fields: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class GetTaskResult:
    """Result of getting a single task."""

    success: bool
    task: Optional[TaskProgress] = None
    phase: str = ""
    project: str = ""
    message: str = ""


@dataclass
class DeleteTaskResult:
    """Result of deleting a task."""

    success: bool
    task_id: str = ""
    phase: str = ""
    project: str = ""
    dependent_tasks_updated: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class UpdateTaskResult:
    """Result of updating a task (extended)."""

    success: bool
    task_id: str = ""
    project: str = ""
    updated_fields: list[str] = field(default_factory=list)
    phase_moved: bool = False
    old_phase: str = ""
    new_phase: str = ""
    message: str = ""


# Column headers for the progress sheet
PROGRESS_SHEET_HEADERS = [
    "フェーズ",      # A
    "タスクID",      # B
    "タスク名",      # C
    "ステータス",    # D
    "ブロッカー",    # E
    "完了日",        # F
    "備考",          # G
    "優先度",        # H (v2: high/medium/low)
    "カテゴリ",      # I (v2: bug/feature/refactor/design/test)
    "依存タスク",    # J (v2: comma-separated task IDs)
]


def task_from_sheet_row(row: list) -> TaskProgress:
    """Create TaskProgress from Google Sheets row.

    Backward compatible: handles both old (A:G) and new (A:J) column layouts.
    """

    def get(idx: int, default: str = "") -> str:
        return row[idx] if idx < len(row) else default

    completed_at = get(5)
    if completed_at:
        try:
            completed_at = datetime.fromisoformat(completed_at)
        except ValueError:
            completed_at = None
    else:
        completed_at = None

    blockers = get(4)
    blockers = [x.strip() for x in blockers.split(",") if x.strip()] if blockers else []

    # Parse new v2 fields (backward compatible - defaults if missing)
    priority = get(7, "medium")
    if priority not in ["high", "medium", "low"]:
        priority = "medium"

    category = get(8, "")

    blocked_by_str = get(9, "")
    blocked_by = [x.strip() for x in blocked_by_str.split(",") if x.strip()] if blocked_by_str else []

    return TaskProgress(
        task_id=get(1),
        name=get(2),
        status=get(3, "not_started"),
        blockers=blockers,
        completed_at=completed_at,
        notes=get(6),
        priority=priority,
        category=category,
        blocked_by=blocked_by,
    )


def task_to_sheet_row(phase: str, task: TaskProgress) -> list:
    """Convert TaskProgress to Google Sheets row.

    Outputs all columns including v2 fields (A:J).
    """
    return [
        phase,                                                    # A: フェーズ
        task.task_id,                                             # B: タスクID
        task.name,                                                # C: タスク名
        task.status,                                              # D: ステータス
        ",".join(task.blockers),                                  # E: ブロッカー
        task.completed_at.isoformat() if task.completed_at else "",  # F: 完了日
        task.notes,                                               # G: 備考
        task.priority,                                            # H: 優先度
        task.category,                                            # I: カテゴリ
        ",".join(task.blocked_by),                                # J: 依存タスク
    ]
