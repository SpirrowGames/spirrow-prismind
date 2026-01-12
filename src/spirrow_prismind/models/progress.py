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


# Column headers for the progress sheet
PROGRESS_SHEET_HEADERS = [
    "フェーズ",
    "タスクID",
    "タスク名",
    "ステータス",
    "ブロッカー",
    "完了日",
    "備考",
]


def task_from_sheet_row(row: list) -> TaskProgress:
    """Create TaskProgress from Google Sheets row."""

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

    return TaskProgress(
        task_id=get(1),
        name=get(2),
        status=get(3, "not_started"),
        blockers=blockers,
        completed_at=completed_at,
        notes=get(6),
    )


def task_to_sheet_row(phase: str, task: TaskProgress) -> list:
    """Convert TaskProgress to Google Sheets row."""
    return [
        phase,
        task.task_id,
        task.name,
        task.status,
        ",".join(task.blockers),
        task.completed_at.isoformat() if task.completed_at else "",
        task.notes,
    ]
