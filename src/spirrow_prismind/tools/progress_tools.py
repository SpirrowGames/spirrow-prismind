"""Progress management tools for Spirrow-Prismind."""

import logging
from datetime import datetime
from typing import Optional

from ..integrations import GoogleSheetsClient, MemoryClient
from ..models import (
    DeleteTaskResult,
    GetProgressResult,
    GetTaskResult,
    PhaseProgress,
    TaskProgress,
    UpdateProgressResult,
    UpdateTaskResult,
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

    def get_task(
        self,
        task_id: str,
        phase: Optional[str] = None,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> GetTaskResult:
        """Get a single task by ID.

        Args:
            task_id: Task ID (e.g., "T01")
            phase: Phase name (required if task_id exists in multiple phases)
            project: Project ID (None for current)
            user: User ID

        Returns:
            GetTaskResult
        """
        user = user or self.user_name

        # Get project config
        if project is None:
            project = self.project_tools.get_current_project_id(user)

        if not project:
            return GetTaskResult(
                success=False,
                message="プロジェクトが選択されていません。",
            )

        config = self.project_tools.get_project_config(project, user)
        if not config:
            return GetTaskResult(
                success=False,
                project=project,
                message=f"プロジェクト '{project}' の設定が見つかりません。",
            )

        try:
            # Check if progress sheet exists
            if not self.sheets.sheet_exists(config.spreadsheet_id, config.sheets.progress):
                return GetTaskResult(
                    success=False,
                    project=project,
                    message=f"進捗シート '{config.sheets.progress}' が見つかりません。",
                )

            # Read current data (A:J for v2 extended columns)
            range_name = f"{config.sheets.progress}!A:J"
            result = self.sheets.read_range(
                spreadsheet_id=config.spreadsheet_id,
                range_name=range_name,
            )

            rows = result.get("values", [])
            if not rows:
                return GetTaskResult(
                    success=False,
                    project=project,
                    message="進捗シートにデータがありません。",
                )

            # Find the task row
            start_row = 0
            if rows[0] and rows[0][0] in ["フェーズ", "Phase"]:
                start_row = 1

            found_tasks = []
            for row in rows[start_row:]:
                if len(row) < 2:
                    continue

                row_phase = row[0] if len(row) > 0 else ""
                row_task_id = row[1] if len(row) > 1 else ""

                if row_task_id == task_id:
                    # If phase is specified, match it too
                    if phase and row_phase != phase:
                        continue
                    task = task_from_sheet_row(row)
                    found_tasks.append((row_phase, task))

            if not found_tasks:
                return GetTaskResult(
                    success=False,
                    project=project,
                    message=f"タスク '{task_id}' が見つかりません。",
                )

            if len(found_tasks) > 1 and not phase:
                phases_list = ", ".join(t[0] for t in found_tasks)
                return GetTaskResult(
                    success=False,
                    project=project,
                    message=f"タスク '{task_id}' が複数のフェーズに存在します: {phases_list}。phase を指定してください。",
                )

            found_phase, found_task = found_tasks[0]
            return GetTaskResult(
                success=True,
                task=found_task,
                phase=found_phase,
                project=project,
                message=f"タスク '{task_id}' を取得しました。",
            )

        except Exception as e:
            logger.error(f"Failed to get task: {e}")
            return GetTaskResult(
                success=False,
                project=project,
                message=f"タスクの取得に失敗しました: {e}",
            )

    def delete_task(
        self,
        task_id: str,
        phase: Optional[str] = None,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> DeleteTaskResult:
        """Delete a task from the progress sheet.

        Also cleans up blocked_by references in other tasks.

        Args:
            task_id: Task ID (e.g., "T01")
            phase: Phase name (required if task_id exists in multiple phases)
            project: Project ID (None for current)
            user: User ID

        Returns:
            DeleteTaskResult
        """
        user = user or self.user_name

        # Get project config
        if project is None:
            project = self.project_tools.get_current_project_id(user)

        if not project:
            return DeleteTaskResult(
                success=False,
                task_id=task_id,
                message="プロジェクトが選択されていません。",
            )

        config = self.project_tools.get_project_config(project, user)
        if not config:
            return DeleteTaskResult(
                success=False,
                task_id=task_id,
                project=project,
                message=f"プロジェクト '{project}' の設定が見つかりません。",
            )

        try:
            # Check if progress sheet exists
            if not self.sheets.sheet_exists(config.spreadsheet_id, config.sheets.progress):
                return DeleteTaskResult(
                    success=False,
                    task_id=task_id,
                    project=project,
                    message=f"進捗シート '{config.sheets.progress}' が見つかりません。",
                )

            # Read current data (A:J for v2 extended columns)
            range_name = f"{config.sheets.progress}!A:J"
            result = self.sheets.read_range(
                spreadsheet_id=config.spreadsheet_id,
                range_name=range_name,
            )

            rows = result.get("values", [])
            if not rows:
                return DeleteTaskResult(
                    success=False,
                    task_id=task_id,
                    project=project,
                    message="進捗シートにデータがありません。",
                )

            # Find the task row
            start_row = 0
            if rows[0] and rows[0][0] in ["フェーズ", "Phase"]:
                start_row = 1

            target_row_idx = -1
            target_phase = ""
            matching_rows = []

            for idx, row in enumerate(rows[start_row:], start=start_row):
                if len(row) < 2:
                    continue

                row_phase = row[0] if len(row) > 0 else ""
                row_task_id = row[1] if len(row) > 1 else ""

                if row_task_id == task_id:
                    if phase and row_phase != phase:
                        continue
                    matching_rows.append((idx, row_phase))

            if not matching_rows:
                return DeleteTaskResult(
                    success=False,
                    task_id=task_id,
                    project=project,
                    message=f"タスク '{task_id}' が見つかりません。",
                )

            if len(matching_rows) > 1 and not phase:
                phases_list = ", ".join(r[1] for r in matching_rows)
                return DeleteTaskResult(
                    success=False,
                    task_id=task_id,
                    project=project,
                    message=f"タスク '{task_id}' が複数のフェーズに存在します: {phases_list}。phase を指定してください。",
                )

            target_row_idx, target_phase = matching_rows[0]

            # Find tasks that have this task in their blocked_by and update them
            dependent_tasks_updated = []
            rows_to_update = []

            for idx, row in enumerate(rows[start_row:], start=start_row):
                if len(row) < 10:
                    continue
                if idx == target_row_idx:
                    continue

                # Check blocked_by column (J = index 9)
                blocked_by_str = row[9] if len(row) > 9 else ""
                if not blocked_by_str:
                    continue

                blocked_by = [x.strip() for x in blocked_by_str.split(",") if x.strip()]
                if task_id in blocked_by:
                    # Remove the deleted task from blocked_by
                    blocked_by.remove(task_id)
                    row_copy = list(row)
                    while len(row_copy) < 10:
                        row_copy.append("")
                    row_copy[9] = ",".join(blocked_by)
                    rows_to_update.append((idx, row_copy))
                    dependent_tasks_updated.append(row[1] if len(row) > 1 else "")

            # Update dependent tasks first
            for idx, updated_row in rows_to_update:
                update_range = f"{config.sheets.progress}!A{idx + 1}:J{idx + 1}"
                self.sheets.update_range(
                    spreadsheet_id=config.spreadsheet_id,
                    range_name=update_range,
                    values=[updated_row],
                )

            # Delete the task row by clearing it
            # Note: Google Sheets API doesn't have a native "delete row" in the simple API
            # We'll clear the row contents. For actual row deletion, use batchUpdate with
            # deleteDimension request, but that's more complex.
            # Alternative: Clear the row and let users manually clean up empty rows
            delete_range = f"{config.sheets.progress}!A{target_row_idx + 1}:J{target_row_idx + 1}"
            self.sheets.update_range(
                spreadsheet_id=config.spreadsheet_id,
                range_name=delete_range,
                values=[[""] * 10],  # Clear all columns
            )

            return DeleteTaskResult(
                success=True,
                task_id=task_id,
                phase=target_phase,
                project=project,
                dependent_tasks_updated=dependent_tasks_updated,
                message=f"タスク '{task_id}' を削除しました。"
                + (f" {len(dependent_tasks_updated)} 件のタスクの依存関係を更新しました。" if dependent_tasks_updated else ""),
            )

        except Exception as e:
            logger.error(f"Failed to delete task: {e}")
            return DeleteTaskResult(
                success=False,
                task_id=task_id,
                project=project,
                message=f"タスクの削除に失敗しました: {e}",
            )

    def update_task(
        self,
        task_id: str,
        phase: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        blocked_by: Optional[list[str]] = None,
        blockers: Optional[list[str]] = None,
        new_phase: Optional[str] = None,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> UpdateTaskResult:
        """Update a task with any combination of fields.

        Supports updating name, description (notes), status, priority, category,
        blocked_by, blockers, and moving to a new phase.

        Args:
            task_id: Task ID (e.g., "T01")
            phase: Current phase name (required if task_id exists in multiple phases)
            name: New task name
            description: New description (stored in notes)
            status: New status (not_started/in_progress/completed/blocked)
            priority: New priority (high/medium/low)
            category: New category
            blocked_by: New blocked_by list
            blockers: New blockers list
            new_phase: Target phase for moving the task
            project: Project ID (None for current)
            user: User ID

        Returns:
            UpdateTaskResult
        """
        user = user or self.user_name

        # Get project config
        if project is None:
            project = self.project_tools.get_current_project_id(user)

        if not project:
            return UpdateTaskResult(
                success=False,
                task_id=task_id,
                message="プロジェクトが選択されていません。",
            )

        config = self.project_tools.get_project_config(project, user)
        if not config:
            return UpdateTaskResult(
                success=False,
                task_id=task_id,
                project=project,
                message=f"プロジェクト '{project}' の設定が見つかりません。",
            )

        # Validate status if provided
        if status is not None:
            valid_statuses = ["not_started", "in_progress", "completed", "blocked"]
            if status not in valid_statuses:
                return UpdateTaskResult(
                    success=False,
                    task_id=task_id,
                    project=project,
                    message=f"無効なステータスです。有効な値: {', '.join(valid_statuses)}",
                )

        # Validate priority if provided
        if priority is not None:
            valid_priorities = ["high", "medium", "low"]
            if priority not in valid_priorities:
                return UpdateTaskResult(
                    success=False,
                    task_id=task_id,
                    project=project,
                    message=f"無効な優先度です。有効な値: {', '.join(valid_priorities)}",
                )

        try:
            # Check if progress sheet exists
            if not self.sheets.sheet_exists(config.spreadsheet_id, config.sheets.progress):
                return UpdateTaskResult(
                    success=False,
                    task_id=task_id,
                    project=project,
                    message=f"進捗シート '{config.sheets.progress}' が見つかりません。",
                )

            # Read current data (A:J for v2 extended columns)
            range_name = f"{config.sheets.progress}!A:J"
            result = self.sheets.read_range(
                spreadsheet_id=config.spreadsheet_id,
                range_name=range_name,
            )

            rows = result.get("values", [])
            if not rows:
                return UpdateTaskResult(
                    success=False,
                    task_id=task_id,
                    project=project,
                    message="進捗シートにデータがありません。",
                )

            # Find the task row
            start_row = 0
            if rows[0] and rows[0][0] in ["フェーズ", "Phase"]:
                start_row = 1

            target_row_idx = -1
            old_phase = ""
            matching_rows = []

            for idx, row in enumerate(rows[start_row:], start=start_row):
                if len(row) < 2:
                    continue

                row_phase = row[0] if len(row) > 0 else ""
                row_task_id = row[1] if len(row) > 1 else ""

                if row_task_id == task_id:
                    if phase and row_phase != phase:
                        continue
                    matching_rows.append((idx, row_phase, row))

            if not matching_rows:
                return UpdateTaskResult(
                    success=False,
                    task_id=task_id,
                    project=project,
                    message=f"タスク '{task_id}' が見つかりません。",
                )

            if len(matching_rows) > 1 and not phase:
                phases_list = ", ".join(r[1] for r in matching_rows)
                return UpdateTaskResult(
                    success=False,
                    task_id=task_id,
                    project=project,
                    message=f"タスク '{task_id}' が複数のフェーズに存在します: {phases_list}。phase を指定してください。",
                )

            target_row_idx, old_phase, target_row = matching_rows[0]
            target_row = list(target_row)  # Make a copy

            # Ensure row has enough columns (10 for v2 extended columns)
            while len(target_row) < 10:
                target_row.append("")

            updated_fields = []
            phase_moved = False
            final_phase = old_phase

            # Update phase (column A)
            if new_phase is not None and new_phase != old_phase:
                target_row[0] = new_phase
                updated_fields.append("phase")
                phase_moved = True
                final_phase = new_phase

            # Update name (column C)
            if name is not None:
                target_row[2] = name
                updated_fields.append("name")

            # Update status (column D)
            if status is not None:
                old_status = target_row[3] if len(target_row) > 3 else ""
                target_row[3] = status
                updated_fields.append("status")

                # Update completed_at if completed
                if status == "completed" and old_status != "completed":
                    target_row[5] = datetime.now().strftime("%Y-%m-%d")
                    updated_fields.append("completed_at")
                elif status != "completed":
                    target_row[5] = ""

            # Update blockers (column E)
            if blockers is not None:
                target_row[4] = ",".join(blockers)
                updated_fields.append("blockers")

            # Update notes/description (column G)
            if description is not None:
                target_row[6] = description
                updated_fields.append("notes")

            # Update priority (column H)
            if priority is not None:
                target_row[7] = priority
                updated_fields.append("priority")

            # Update category (column I)
            if category is not None:
                target_row[8] = category
                updated_fields.append("category")

            # Update blocked_by (column J)
            if blocked_by is not None:
                target_row[9] = ",".join(blocked_by)
                updated_fields.append("blocked_by")

            if not updated_fields:
                return UpdateTaskResult(
                    success=True,
                    task_id=task_id,
                    project=project,
                    updated_fields=[],
                    phase_moved=False,
                    old_phase=old_phase,
                    new_phase=old_phase,
                    message="更新するフィールドがありません。",
                )

            # Write back to Sheets (A:J for v2 extended columns)
            update_range = f"{config.sheets.progress}!A{target_row_idx + 1}:J{target_row_idx + 1}"
            self.sheets.update_range(
                spreadsheet_id=config.spreadsheet_id,
                range_name=update_range,
                values=[target_row],
            )

            # Update session state if status changed
            if status is not None:
                session_state = self.memory.get_session_state(project, user)
                if session_state:
                    if status == "in_progress":
                        session_state.current_task = task_id
                    if status == "completed":
                        session_state.last_completed = task_id
                    if blockers is not None:
                        session_state.blockers = blockers
                    self.memory.save_session_state(session_state)

            move_msg = f" (フェーズ: {old_phase} → {final_phase})" if phase_moved else ""
            return UpdateTaskResult(
                success=True,
                task_id=task_id,
                project=project,
                updated_fields=updated_fields,
                phase_moved=phase_moved,
                old_phase=old_phase,
                new_phase=final_phase,
                message=f"タスク '{task_id}' を更新しました。{move_msg}",
            )

        except Exception as e:
            logger.error(f"Failed to update task: {e}")
            return UpdateTaskResult(
                success=False,
                task_id=task_id,
                project=project,
                message=f"タスクの更新に失敗しました: {e}",
            )
