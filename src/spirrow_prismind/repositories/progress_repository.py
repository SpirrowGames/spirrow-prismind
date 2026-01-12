"""Progress repository - manages project progress in Google Sheets."""

import os
from datetime import datetime
from typing import Optional

from ..integrations.google_sheets import GoogleSheetsClient
from ..models.progress import (
    PROGRESS_SHEET_HEADERS,
    GetProgressResult,
    PhaseProgress,
    TaskDefinition,
    TaskProgress,
    UpdateProgressResult,
    task_from_sheet_row,
    task_to_sheet_row,
)


class ProgressRepository:
    """Repository for managing project progress."""

    def __init__(
        self,
        sheets_client: Optional[GoogleSheetsClient] = None,
        spreadsheet_id: Optional[str] = None,
    ):
        """Initialize the progress repository.

        Args:
            sheets_client: Google Sheets client (creates new if not provided)
            spreadsheet_id: ID of the progress spreadsheet
        """
        self.sheets_client = sheets_client or GoogleSheetsClient()
        self.spreadsheet_id = spreadsheet_id or os.getenv("PROGRESS_SHEET_ID", "")

    def _get_project_sheet_name(self, project: str) -> str:
        """Get the sheet name for a project."""
        return project

    def _ensure_project_sheet(self, project: str) -> None:
        """Ensure the project's progress sheet exists."""
        if not self.spreadsheet_id:
            raise ValueError("PROGRESS_SHEET_ID not configured")

        sheet_name = self._get_project_sheet_name(project)
        try:
            sheet_names = self.sheets_client.get_sheet_names(self.spreadsheet_id)
            if sheet_name not in sheet_names:
                raise ValueError(
                    f"Sheet '{sheet_name}' not found. Please create it manually."
                )

            # Check if headers exist
            values = self.sheets_client.get_sheet_values(
                self.spreadsheet_id, f"{sheet_name}!A1:G1"
            )
            if not values or values[0] != PROGRESS_SHEET_HEADERS:
                # Set headers
                self.sheets_client.update_sheet_values(
                    self.spreadsheet_id,
                    f"{sheet_name}!A1:G1",
                    [PROGRESS_SHEET_HEADERS],
                )
        except Exception as e:
            raise RuntimeError(f"Failed to ensure progress sheet: {e}")

    def get_progress(
        self,
        project: str,
        phase: Optional[str] = None,
        include_completed: bool = False,
    ) -> GetProgressResult:
        """Get project progress.

        Args:
            project: Project name
            phase: Filter by specific phase
            include_completed: Include completed tasks

        Returns:
            Progress information
        """
        try:
            sheet_name = self._get_project_sheet_name(project)
            values = self.sheets_client.get_sheet_values(
                self.spreadsheet_id, f"{sheet_name}!A2:G"
            )

            # Group by phase
            phases_dict: dict[str, list[TaskProgress]] = {}
            for row in values:
                if not row:
                    continue

                phase_name = row[0] if row else ""
                if phase and phase_name != phase:
                    continue

                task = task_from_sheet_row(row)

                if not include_completed and task.status == "completed":
                    continue

                if phase_name not in phases_dict:
                    phases_dict[phase_name] = []
                phases_dict[phase_name].append(task)

            # Convert to PhaseProgress list
            phases = []
            current_phase = ""
            for phase_name, tasks in phases_dict.items():
                # Determine phase status
                all_completed = all(t.status == "completed" for t in tasks)
                any_in_progress = any(t.status == "in_progress" for t in tasks)

                if all_completed:
                    status = "completed"
                elif any_in_progress:
                    status = "in_progress"
                    current_phase = phase_name
                else:
                    status = "not_started"

                phases.append(
                    PhaseProgress(
                        phase=phase_name,
                        status=status,
                        tasks=tasks,
                    )
                )

                # Find current phase if not set
                if not current_phase and status != "completed":
                    current_phase = phase_name

            return GetProgressResult(
                success=True,
                project=project,
                current_phase=current_phase,
                phases=phases,
                message=f"Found {len(phases)} phases",
            )
        except Exception as e:
            return GetProgressResult(
                success=False,
                project=project,
                message=f"Failed to get progress: {e}",
            )

    def update_task(
        self,
        project: str,
        task_id: str,
        status: Optional[str] = None,
        blockers: Optional[list[str]] = None,
        notes: Optional[str] = None,
    ) -> UpdateProgressResult:
        """Update a task's status.

        Args:
            project: Project name
            task_id: Task ID (e.g., "T01")
            status: New status
            blockers: Updated blockers list
            notes: Updated notes

        Returns:
            Update result
        """
        try:
            sheet_name = self._get_project_sheet_name(project)

            # Find the row with this task_id
            row_num = self.sheets_client.find_row_by_value(
                self.spreadsheet_id,
                sheet_name,
                1,  # Task ID column (0-based)
                task_id,
            )

            if row_num is None:
                return UpdateProgressResult(
                    success=False,
                    project=project,
                    task_id=task_id,
                    message=f"Task not found: {task_id}",
                )

            # Get current row
            values = self.sheets_client.get_sheet_values(
                self.spreadsheet_id,
                f"{sheet_name}!A{row_num}:G{row_num}",
            )
            if not values:
                return UpdateProgressResult(
                    success=False,
                    project=project,
                    task_id=task_id,
                    message=f"Failed to read task: {task_id}",
                )

            row = values[0]
            task = task_from_sheet_row(row)
            phase = row[0]
            updated_fields = []

            # Apply updates
            if status is not None:
                task.status = status
                updated_fields.append("status")
                if status == "completed":
                    task.completed_at = datetime.now()
                    updated_fields.append("completed_at")

            if blockers is not None:
                task.blockers = blockers
                updated_fields.append("blockers")

            if notes is not None:
                task.notes = notes
                updated_fields.append("notes")

            # Write back
            new_row = task_to_sheet_row(phase, task)
            self.sheets_client.update_row(
                self.spreadsheet_id,
                sheet_name,
                row_num,
                new_row,
            )

            return UpdateProgressResult(
                success=True,
                project=project,
                task_id=task_id,
                updated_fields=updated_fields,
                message=f"Updated task {task_id}",
            )
        except Exception as e:
            return UpdateProgressResult(
                success=False,
                project=project,
                task_id=task_id,
                message=f"Failed to update task: {e}",
            )

    def add_task(
        self,
        project: str,
        task_def: TaskDefinition,
    ) -> UpdateProgressResult:
        """Add a new task.

        Args:
            project: Project name
            task_def: Task definition

        Returns:
            Update result
        """
        try:
            sheet_name = self._get_project_sheet_name(project)

            task = TaskProgress(
                task_id=task_def.task_id,
                name=task_def.name,
                status="not_started",
                notes=task_def.description,
            )

            row = task_to_sheet_row(task_def.phase, task)
            self.sheets_client.append_sheet_values(
                self.spreadsheet_id,
                f"{sheet_name}!A:G",
                [row],
            )

            return UpdateProgressResult(
                success=True,
                project=project,
                task_id=task_def.task_id,
                updated_fields=["created"],
                message=f"Added task {task_def.task_id}",
            )
        except Exception as e:
            return UpdateProgressResult(
                success=False,
                project=project,
                task_id=task_def.task_id,
                message=f"Failed to add task: {e}",
            )

    def get_current_task(self, project: str) -> Optional[tuple[str, str]]:
        """Get the current phase and task for a project.

        Args:
            project: Project name

        Returns:
            Tuple of (phase, task_id) or None
        """
        result = self.get_progress(project, include_completed=False)
        if not result.success or not result.phases:
            return None

        for phase in result.phases:
            for task in phase.tasks:
                if task.status == "in_progress":
                    return (phase.phase, task.task_id)

        # Return first not_started task
        for phase in result.phases:
            for task in phase.tasks:
                if task.status == "not_started":
                    return (phase.phase, task.task_id)

        return None
