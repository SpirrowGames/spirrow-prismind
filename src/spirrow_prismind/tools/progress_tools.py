"""Progress management tools for Spirrow-Prismind."""

import logging
from datetime import datetime
from typing import Optional

from ..integrations import GoogleSheetsClient, MemoryClient
from ..models import (
    GetProgressResult,
    PhaseProgress,
    TaskProgress,
    UpdateProgressResult,
    task_from_sheet_row,
    task_to_sheet_row,
    PROGRESS_SHEET_HEADERS,
)
from .project_tools import ProjectTools

logger = logging.getLogger(__name__)


class ProgressTools:
    """Tools for progress management with Google Sheets integration."""

    def __init__(
        self,
        sheets_client: GoogleSheetsClient,
        memory_client: MemoryClient,
        project_tools: ProjectTools,
        user_name: str = "default",
    ):
        """Initialize progress tools.

        Args:
            sheets_client: Google Sheets client
            memory_client: Memory client for session state
            project_tools: Project tools for config access
            user_name: Default user ID
        """
        self.sheets = sheets_client
        self.memory = memory_client
        self.project_tools = project_tools
        self.user_name = user_name

    def get_progress(
        self,
        project: Optional[str] = None,
        phase: Optional[str] = None,
        user: Optional[str] = None,
    ) -> GetProgressResult:
        """Get progress from Google Sheets.

        Args:
            project: Project ID (None for current)
            phase: Filter by specific phase (None for all)
            user: User ID

        Returns:
            GetProgressResult
        """
        user = user or self.user_name

        # Get project config
        if project is None:
            project = self.project_tools.get_current_project_id(user)

        if not project:
            return GetProgressResult(
                success=False,
                message="プロジェクトが選択されていません。",
            )

        config = self.project_tools.get_project_config(project, user)
        if not config:
            return GetProgressResult(
                success=False,
                project=project,
                message=f"プロジェクト '{project}' の設定が見つかりません。",
            )

        try:
            # Check if progress sheet exists
            if not self.sheets.sheet_exists(config.spreadsheet_id, config.sheets.progress):
                return GetProgressResult(
                    success=False,
                    project=project,
                    message=f"進捗シート '{config.sheets.progress}' が見つかりません。プロジェクト設定を確認してください。",
                )

            # Read from Google Sheets (A:J for v2 extended columns)
            range_name = f"{config.sheets.progress}!A:J"
            result = self.sheets.read_range(
                spreadsheet_id=config.spreadsheet_id,
                range_name=range_name,
            )

            rows = result.get("values", [])

            if not rows:
                return GetProgressResult(
                    success=True,
                    project=project,
                    current_phase="",
                    phases=[],
                    message="進捗データがありません。",
                )

            # Skip header row
            start_row = 0
            if rows and rows[0] and rows[0][0] in ["フェーズ", "Phase"]:
                start_row = 1

            # Parse rows into phases and tasks
            phases_dict: dict[str, PhaseProgress] = {}
            current_phase = ""

            for row in rows[start_row:]:
                if len(row) < 3:
                    continue

                phase_name = row[0] if len(row) > 0 else ""
                if not phase_name:
                    continue

                # Filter by phase if specified
                if phase and phase_name != phase:
                    continue

                # Create or get phase
                if phase_name not in phases_dict:
                    phases_dict[phase_name] = PhaseProgress(
                        phase=phase_name,
                        status="not_started",
                        tasks=[],
                    )

                # Parse task
                task = task_from_sheet_row(row)
                phases_dict[phase_name].tasks.append(task)

                # Track current phase (first in_progress phase)
                if task.status == "in_progress" and not current_phase:
                    current_phase = phase_name

            # Calculate phase statuses
            phases = []
            for phase_name, phase_progress in phases_dict.items():
                # Determine phase status from tasks
                all_completed = all(t.status == "completed" for t in phase_progress.tasks)
                any_started = any(t.status in ["in_progress", "completed"] for t in phase_progress.tasks)
                any_blocked = any(t.status == "blocked" for t in phase_progress.tasks)

                if all_completed and phase_progress.tasks:
                    phase_progress.status = "completed"
                elif any_blocked:
                    phase_progress.status = "blocked"
                elif any_started:
                    phase_progress.status = "in_progress"
                else:
                    phase_progress.status = "not_started"

                phases.append(phase_progress)

            # Sort phases
            phases.sort(key=lambda p: p.phase)

            # If no current phase found, use first non-completed
            if not current_phase:
                for p in phases:
                    if p.status != "completed":
                        current_phase = p.phase
                        break

            return GetProgressResult(
                success=True,
                project=project,
                current_phase=current_phase,
                phases=phases,
                message=f"{len(phases)} フェーズ、{sum(len(p.tasks) for p in phases)} タスクを取得しました。",
            )

        except Exception as e:
            logger.error(f"Failed to get progress: {e}")
            return GetProgressResult(
                success=False,
                project=project,
                message=f"進捗の取得に失敗しました: {e}",
            )

    def update_task_status(
        self,
        task_id: str,
        status: str,
        phase: Optional[str] = None,
        blockers: Optional[list[str]] = None,
        notes: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        blocked_by: Optional[list[str]] = None,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> UpdateProgressResult:
        """Update a task's status in Google Sheets.

        Args:
            task_id: Task ID (e.g., "T01")
            status: New status (not_started/in_progress/completed/blocked)
            phase: Phase name (required if task_id is ambiguous)
            blockers: New blockers list (None to keep)
            notes: Notes (None to keep)
            priority: New priority (high/medium/low, None to keep)
            category: New category (bug/feature/refactor/design/test, None to keep)
            blocked_by: New blocked_by list (None to keep)
            project: Project ID (None for current)
            user: User ID

        Returns:
            UpdateProgressResult
        """
        user = user or self.user_name

        # Validate status
        valid_statuses = ["not_started", "in_progress", "completed", "blocked"]
        if status not in valid_statuses:
            return UpdateProgressResult(
                success=False,
                task_id=task_id,
                message=f"無効なステータスです。有効な値: {', '.join(valid_statuses)}",
            )

        # Get project config
        if project is None:
            project = self.project_tools.get_current_project_id(user)

        if not project:
            return UpdateProgressResult(
                success=False,
                task_id=task_id,
                message="プロジェクトが選択されていません。",
            )

        config = self.project_tools.get_project_config(project, user)
        if not config:
            return UpdateProgressResult(
                success=False,
                project=project,
                task_id=task_id,
                message=f"プロジェクト '{project}' の設定が見つかりません。",
            )

        try:
            # Check if progress sheet exists
            if not self.sheets.sheet_exists(config.spreadsheet_id, config.sheets.progress):
                return UpdateProgressResult(
                    success=False,
                    project=project,
                    task_id=task_id,
                    message=f"進捗シート '{config.sheets.progress}' が見つかりません。プロジェクト設定を確認してください。",
                )

            # Read current data (A:J for v2 extended columns)
            range_name = f"{config.sheets.progress}!A:J"
            result = self.sheets.read_range(
                spreadsheet_id=config.spreadsheet_id,
                range_name=range_name,
            )

            rows = result.get("values", [])
            if not rows:
                return UpdateProgressResult(
                    success=False,
                    project=project,
                    task_id=task_id,
                    message="進捗シートにデータがありません。",
                )

            # Find the task row
            start_row = 0
            if rows[0] and rows[0][0] in ["フェーズ", "Phase"]:
                start_row = 1

            target_row_idx = -1
            for idx, row in enumerate(rows[start_row:], start=start_row):
                if len(row) < 2:
                    continue

                row_phase = row[0] if len(row) > 0 else ""
                row_task_id = row[1] if len(row) > 1 else ""

                if row_task_id == task_id:
                    # If phase is specified, match it too
                    if phase and row_phase != phase:
                        continue
                    target_row_idx = idx
                    break

            if target_row_idx < 0:
                return UpdateProgressResult(
                    success=False,
                    project=project,
                    task_id=task_id,
                    message=f"タスク '{task_id}' が見つかりません。",
                )

            # Update the row
            updated_fields = ["status"]
            target_row = rows[target_row_idx]

            # Ensure row has enough columns (10 for v2 extended columns)
            while len(target_row) < 10:
                target_row.append("")

            # Update status
            old_status = target_row[3] if len(target_row) > 3 else ""
            target_row[3] = status

            # Update completed_at if completed
            if status == "completed" and old_status != "completed":
                target_row[5] = datetime.now().strftime("%Y-%m-%d")
                updated_fields.append("completed_at")
            elif status != "completed":
                target_row[5] = ""

            # Update blockers if provided
            if blockers is not None:
                target_row[4] = ",".join(blockers)
                updated_fields.append("blockers")

            # Update notes if provided
            if notes is not None:
                target_row[6] = notes
                updated_fields.append("notes")

            # Update v2 extended fields
            if priority is not None:
                valid_priorities = ["high", "medium", "low"]
                if priority in valid_priorities:
                    target_row[7] = priority
                    updated_fields.append("priority")

            if category is not None:
                target_row[8] = category
                updated_fields.append("category")

            if blocked_by is not None:
                target_row[9] = ",".join(blocked_by)
                updated_fields.append("blocked_by")

            # Write back to Sheets (A:J for v2 extended columns)
            update_range = f"{config.sheets.progress}!A{target_row_idx + 1}:J{target_row_idx + 1}"
            self.sheets.update_range(
                spreadsheet_id=config.spreadsheet_id,
                range_name=update_range,
                values=[target_row],
            )

            # Also update session state in memory
            session_state = self.memory.get_session_state(project, user)
            if session_state:
                session_state.current_task = task_id if status == "in_progress" else session_state.current_task
                if status == "completed":
                    session_state.last_completed = task_id
                if blockers is not None:
                    session_state.blockers = blockers
                self.memory.save_session_state(session_state)

            return UpdateProgressResult(
                success=True,
                project=project,
                task_id=task_id,
                updated_fields=updated_fields,
                message=f"タスク '{task_id}' を '{status}' に更新しました。",
            )

        except Exception as e:
            logger.error(f"Failed to update progress: {e}")
            return UpdateProgressResult(
                success=False,
                project=project,
                task_id=task_id,
                message=f"進捗の更新に失敗しました: {e}",
            )

    def add_task(
        self,
        phase: str,
        task_id: str,
        name: str,
        description: str = "",
        priority: str = "medium",
        category: str = "",
        blocked_by: Optional[list[str]] = None,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> UpdateProgressResult:
        """Add a new task to the progress sheet.

        Args:
            phase: Phase name (e.g., "Phase 4")
            task_id: Task ID (e.g., "T01")
            name: Task name
            description: Task description (stored in notes)
            priority: Task priority (high/medium/low, default: medium)
            category: Task category (bug/feature/refactor/design/test etc.)
            blocked_by: List of task IDs this task depends on (e.g., ["T01", "T02"])
            project: Project ID (None for current)
            user: User ID

        Returns:
            UpdateProgressResult
        """
        user = user or self.user_name

        # Get project config
        if project is None:
            project = self.project_tools.get_current_project_id(user)

        if not project:
            return UpdateProgressResult(
                success=False,
                task_id=task_id,
                message="プロジェクトが選択されていません。",
            )

        config = self.project_tools.get_project_config(project, user)
        if not config:
            return UpdateProgressResult(
                success=False,
                project=project,
                task_id=task_id,
                message=f"プロジェクト '{project}' の設定が見つかりません。",
            )

        try:
            # Check if progress sheet exists
            if not self.sheets.sheet_exists(config.spreadsheet_id, config.sheets.progress):
                return UpdateProgressResult(
                    success=False,
                    project=project,
                    task_id=task_id,
                    message=f"進捗シート '{config.sheets.progress}' が見つかりません。プロジェクト設定を確認してください。",
                )

            # Validate priority
            valid_priorities = ["high", "medium", "low"]
            if priority not in valid_priorities:
                priority = "medium"

            # Create task row with v2 extended fields
            task = TaskProgress(
                task_id=task_id,
                name=name,
                status="not_started",
                blockers=[],
                notes=description,
                priority=priority,
                category=category,
                blocked_by=blocked_by or [],
            )

            row = task_to_sheet_row(phase, task)

            # Append to sheet (A:J for v2 extended columns)
            self.sheets.append_rows(
                spreadsheet_id=config.spreadsheet_id,
                range_name=f"{config.sheets.progress}!A:J",
                values=[row],
            )

            return UpdateProgressResult(
                success=True,
                project=project,
                task_id=task_id,
                updated_fields=["phase", "task_id", "name", "status"],
                message=f"タスク '{task_id}: {name}' を追加しました。",
            )

        except Exception as e:
            logger.error(f"Failed to add task: {e}")
            return UpdateProgressResult(
                success=False,
                project=project,
                task_id=task_id,
                message=f"タスクの追加に失敗しました: {e}",
            )

    def complete_task(
        self,
        task_id: str,
        phase: Optional[str] = None,
        notes: Optional[str] = None,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> UpdateProgressResult:
        """Mark a task as completed.

        Convenience method for update_task_status with status="completed".

        Args:
            task_id: Task ID
            phase: Phase name (if needed)
            notes: Completion notes
            project: Project ID
            user: User ID

        Returns:
            UpdateProgressResult
        """
        return self.update_task_status(
            task_id=task_id,
            status="completed",
            phase=phase,
            notes=notes,
            project=project,
            user=user,
        )

    def start_task(
        self,
        task_id: str,
        phase: Optional[str] = None,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> UpdateProgressResult:
        """Mark a task as in progress.

        Convenience method for update_task_status with status="in_progress".

        Args:
            task_id: Task ID
            phase: Phase name (if needed)
            project: Project ID
            user: User ID

        Returns:
            UpdateProgressResult
        """
        return self.update_task_status(
            task_id=task_id,
            status="in_progress",
            phase=phase,
            project=project,
            user=user,
        )

    def block_task(
        self,
        task_id: str,
        blockers: list[str],
        phase: Optional[str] = None,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> UpdateProgressResult:
        """Mark a task as blocked.

        Args:
            task_id: Task ID
            blockers: List of blockers
            phase: Phase name (if needed)
            project: Project ID
            user: User ID

        Returns:
            UpdateProgressResult
        """
        return self.update_task_status(
            task_id=task_id,
            status="blocked",
            phase=phase,
            blockers=blockers,
            project=project,
            user=user,
        )
