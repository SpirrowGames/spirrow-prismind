"""Session management tools for Spirrow-Prismind."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from ..integrations import (
    GoogleSheetsClient,
    MemoryClient,
    RAGClient,
    SessionState,
)
from ..models import (
    DocReference,
    EndSessionResult,
    SaveSessionResult,
    SessionContext,
    UpdateSummaryResult,
)
from .project_tools import ProjectTools

logger = logging.getLogger(__name__)


class SessionTools:
    """Tools for managing sessions."""

    def __init__(
        self,
        rag_client: RAGClient,
        memory_client: MemoryClient,
        sheets_client: GoogleSheetsClient,
        project_tools: ProjectTools,
        user_name: str = "default",
    ):
        """Initialize session tools.
        
        Args:
            rag_client: RAG client for document lookup
            memory_client: Memory client for session state
            sheets_client: Google Sheets client for progress
            project_tools: Project tools for config access
            user_name: Default user ID
        """
        self.rag = rag_client
        self.memory = memory_client
        self.sheets = sheets_client
        self.project_tools = project_tools
        self.user_name = user_name
        
        # Track session start time
        self._session_start: Optional[datetime] = None
        self._current_project: Optional[str] = None
        self._current_user: Optional[str] = None

    def _get_current_project(self, user: str) -> Optional[str]:
        """Get current project, preferring Memory Server over local state.

        This ensures switch_project changes are properly reflected.

        Args:
            user: User ID

        Returns:
            Current project ID or None
        """
        # MemoryServerを優先参照（switch_projectの変更を反映）
        current = self.memory.get_current_project(user)
        if current and current.project_id:
            # ローカル状態も同期
            self._current_project = current.project_id
            return current.project_id

        # フォールバック: ローカル状態
        return self._current_project

    def start_session(
        self,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> SessionContext:
        """Start a session and load saved state.
        
        Args:
            project: Project ID (None to use current)
            user: User ID (uses default if None)
            
        Returns:
            SessionContext with loaded state and recommendations
        """
        user = user or self.user_name
        
        # Get project (from parameter or current)
        if project is None:
            current = self.memory.get_current_project(user)
            if current:
                project = current.project_id
        
        if not project:
            return SessionContext(
                project="",
                project_name="",
                user=user,
                started_at=datetime.now(),
                current_phase="",
                current_task="",
                last_completed="",
                blockers=[],
                recommended_docs=[],
                notes="プロジェクトが指定されていません。switch_project でプロジェクトを選択してください。",
            )
        
        # Get project config
        config = self.project_tools.get_project_config(project, user)
        if not config:
            return SessionContext(
                project=project,
                project_name="",
                user=user,
                started_at=datetime.now(),
                current_phase="",
                current_task="",
                last_completed="",
                blockers=[],
                recommended_docs=[],
                notes=f"プロジェクト '{project}' の設定が見つかりません。",
            )
        
        # Load session state from Memory
        session_state = self.memory.get_session_state(project, user)
        
        # Track session
        self._session_start = datetime.now()
        self._current_project = project
        self._current_user = user
        
        # Set as current project
        self.memory.set_current_project(user, project)
        
        # Build context
        if session_state:
            current_phase = session_state.current_phase
            current_task = session_state.current_task
            last_completed = session_state.last_completed
            blockers = session_state.blockers
            notes = session_state.notes
        else:
            current_phase = ""
            current_task = ""
            last_completed = ""
            blockers = []
            notes = "新しいセッションです。"
        
        # Get recommended documents
        recommended_docs = self._get_recommended_docs(
            project=project,
            current_phase=current_phase,
            current_task=current_task,
        )
        
        return SessionContext(
            project=project,
            project_name=config.name,
            user=user,
            started_at=self._session_start,
            current_phase=current_phase,
            current_task=current_task,
            last_completed=last_completed,
            blockers=blockers,
            recommended_docs=recommended_docs,
            notes=notes,
        )

    def end_session(
        self,
        summary: Optional[str] = None,
        next_action: Optional[str] = None,
        blockers: Optional[list[str]] = None,
        notes: Optional[str] = None,
        user: Optional[str] = None,
    ) -> EndSessionResult:
        """End the session and save state.
        
        Args:
            summary: Work summary for this session
            next_action: What to do next
            blockers: Updated blockers list
            notes: Notes for next session
            user: User ID (uses default if None)
            
        Returns:
            EndSessionResult
        """
        user = user or self._current_user or self.user_name
        project = self._get_current_project(user)

        if not project:
            return EndSessionResult(
                success=False,
                session_duration=timedelta(0),
                saved_to=[],
                message="アクティブなセッションがありません。",
            )
        
        # Calculate duration
        if self._session_start:
            duration = datetime.now() - self._session_start
        else:
            duration = timedelta(0)
        
        # Load existing state
        existing_state = self.memory.get_session_state(project, user)
        
        # Build updated state
        state = SessionState(
            project=project,
            user=user,
            current_phase=existing_state.current_phase if existing_state else "",
            current_task=existing_state.current_task if existing_state else "",
            last_completed=existing_state.last_completed if existing_state else "",
            blockers=blockers if blockers is not None else (existing_state.blockers if existing_state else []),
            notes=notes if notes is not None else "",
            last_summary=summary or "",
            next_action=next_action or "",
        )
        
        # Save to Memory
        saved_to = []
        result = self.memory.save_session_state(state)
        if result.success:
            saved_to.append("MCP Memory Server")
        else:
            logger.warning(f"Memory Server save failed: {result.message}")

        # Clear session tracking
        self._session_start = None
        self._current_project = None
        self._current_user = None

        duration_str = self._format_duration(duration)
        if saved_to:
            message = f"セッション状態を保存しました。（所要時間: {duration_str}）"
        else:
            message = f"セッションを終了しました。（所要時間: {duration_str}）（状態は永続化されていません）"

        return EndSessionResult(
            success=True,
            session_duration=duration,
            saved_to=saved_to,
            message=message,
        )

    def save_session(
        self,
        summary: Optional[str] = None,
        next_action: Optional[str] = None,
        blockers: Optional[list[str]] = None,
        notes: Optional[str] = None,
        current_phase: Optional[str] = None,
        current_task: Optional[str] = None,
        user: Optional[str] = None,
    ) -> SaveSessionResult:
        """Save session state without ending.
        
        Args:
            summary: Work summary
            next_action: What to do next
            blockers: Updated blockers list
            notes: Notes
            current_phase: Update current phase
            current_task: Update current task
            user: User ID (uses default if None)

        Returns:
            SaveSessionResult
        """
        user = user or self._current_user or self.user_name
        project = self._get_current_project(user)

        if not project:
            return SaveSessionResult(
                success=False,
                saved_to=[],
                message="アクティブなプロジェクトがありません。",
            )

        # Load existing state
        existing_state = self.memory.get_session_state(project, user)

        # Build updated state
        state = SessionState(
            project=project,
            user=user,
            current_phase=current_phase if current_phase is not None else (existing_state.current_phase if existing_state else ""),
            current_task=current_task if current_task is not None else (existing_state.current_task if existing_state else ""),
            last_completed=existing_state.last_completed if existing_state else "",
            blockers=blockers if blockers is not None else (existing_state.blockers if existing_state else []),
            notes=notes if notes is not None else (existing_state.notes if existing_state else ""),
            last_summary=summary if summary is not None else (existing_state.last_summary if existing_state else ""),
            next_action=next_action if next_action is not None else (existing_state.next_action if existing_state else ""),
        )
        
        # Save to Memory
        saved_to = []
        result = self.memory.save_session_state(state)
        if result.success:
            saved_to.append("MCP Memory Server")
        else:
            logger.warning(f"Memory Server save failed: {result.message}")

        if saved_to:
            message = "セッション状態を保存しました。"
        else:
            message = "セッション状態を更新しました。（永続化されていません - Memory Serverの接続を確認してください）"

        return SaveSessionResult(
            success=True,
            saved_to=saved_to,
            message=message,
        )

    def update_progress(
        self,
        current_phase: Optional[str] = None,
        current_task: Optional[str] = None,
        completed_task: Optional[str] = None,
        blockers: Optional[list[str]] = None,
        user: Optional[str] = None,
    ) -> SaveSessionResult:
        """Update progress in the session.
        
        Args:
            current_phase: New current phase
            current_task: New current task
            completed_task: Task that was just completed
            blockers: Updated blockers
            user: User ID

        Returns:
            SaveSessionResult
        """
        user = user or self._current_user or self.user_name
        project = self._get_current_project(user)

        if not project:
            return SaveSessionResult(
                success=False,
                saved_to=[],
                message="アクティブなプロジェクトがありません。",
            )

        # Load existing state
        existing_state = self.memory.get_session_state(project, user)
        
        # Build updated state
        last_completed = completed_task if completed_task else (existing_state.last_completed if existing_state else "")
        
        state = SessionState(
            project=project,
            user=user,
            current_phase=current_phase if current_phase is not None else (existing_state.current_phase if existing_state else ""),
            current_task=current_task if current_task is not None else (existing_state.current_task if existing_state else ""),
            last_completed=last_completed,
            blockers=blockers if blockers is not None else (existing_state.blockers if existing_state else []),
            notes=existing_state.notes if existing_state else "",
            last_summary=existing_state.last_summary if existing_state else "",
            next_action=existing_state.next_action if existing_state else "",
        )
        
        # Save
        saved_to = []
        result = self.memory.save_session_state(state)
        if result.success:
            saved_to.append("MCP Memory Server")
        else:
            logger.warning(f"Memory Server save failed: {result.message}")

        if saved_to:
            message = "進捗を更新しました。"
        else:
            message = "進捗を更新しました。（永続化されていません）"

        return SaveSessionResult(
            success=True,
            saved_to=saved_to,
            message=message,
        )

    def update_summary(
        self,
        project: Optional[str] = None,
        description: Optional[str] = None,
        current_phase: Optional[str] = None,
        completed_tasks: Optional[int] = None,
        total_tasks: Optional[int] = None,
        custom_fields: Optional[dict[str, str]] = None,
        user: Optional[str] = None,
    ) -> UpdateSummaryResult:
        """Update the summary sheet with project information.

        Args:
            project: Project ID (None for current)
            description: Project description to update
            current_phase: Current phase name
            completed_tasks: Number of completed tasks
            total_tasks: Total number of tasks
            custom_fields: Additional key-value pairs to add/update
            user: User ID

        Returns:
            UpdateSummaryResult
        """
        user = user or self.user_name

        # Get project config
        if project is None:
            project = self.project_tools.get_current_project_id(user)

        if not project:
            return UpdateSummaryResult(
                success=False,
                message="プロジェクトが選択されていません。",
            )

        config = self.project_tools.get_project_config(project, user)
        if not config:
            return UpdateSummaryResult(
                success=False,
                project=project,
                message=f"プロジェクト '{project}' の設定が見つかりません。",
            )

        try:
            # Check if summary sheet exists
            if not self.sheets.sheet_exists(config.spreadsheet_id, config.sheets.summary):
                return UpdateSummaryResult(
                    success=False,
                    project=project,
                    message=f"サマリシート '{config.sheets.summary}' が見つかりません。",
                )

            # Read current summary data
            range_name = f"{config.sheets.summary}!A:B"
            result = self.sheets.read_range(
                spreadsheet_id=config.spreadsheet_id,
                range_name=range_name,
            )

            rows = result.get("values", [])
            updated_fields = []

            # Build a map of key -> row index
            key_to_row: dict[str, int] = {}
            for idx, row in enumerate(rows):
                if row and len(row) >= 1:
                    key_to_row[row[0]] = idx

            # Update specific fields
            updates_to_make: list[tuple[int, str, str]] = []

            if description is not None and "説明" in key_to_row:
                row_idx = key_to_row["説明"]
                updates_to_make.append((row_idx, "説明", description))
                updated_fields.append("説明")

            if current_phase is not None and "現在のフェーズ" in key_to_row:
                row_idx = key_to_row["現在のフェーズ"]
                updates_to_make.append((row_idx, "現在のフェーズ", current_phase))
                updated_fields.append("現在のフェーズ")

            if completed_tasks is not None and "完了タスク" in key_to_row:
                row_idx = key_to_row["完了タスク"]
                updates_to_make.append((row_idx, "完了タスク", str(completed_tasks)))
                updated_fields.append("完了タスク")

            if total_tasks is not None and "全タスク" in key_to_row:
                row_idx = key_to_row["全タスク"]
                updates_to_make.append((row_idx, "全タスク", str(total_tasks)))
                updated_fields.append("全タスク")

            # Always update 最終更新
            if "最終更新" in key_to_row:
                row_idx = key_to_row["最終更新"]
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                updates_to_make.append((row_idx, "最終更新", now_str))
                updated_fields.append("最終更新")

            # Handle custom fields - append to the end if not exists
            if custom_fields:
                max_row = len(rows)
                for key, value in custom_fields.items():
                    if key in key_to_row:
                        row_idx = key_to_row[key]
                        updates_to_make.append((row_idx, key, value))
                    else:
                        # Append new row
                        updates_to_make.append((max_row, key, value))
                        max_row += 1
                    updated_fields.append(key)

            # Apply updates
            for row_idx, key, value in updates_to_make:
                update_range = f"{config.sheets.summary}!A{row_idx + 1}:B{row_idx + 1}"
                self.sheets.update_range(
                    spreadsheet_id=config.spreadsheet_id,
                    range_name=update_range,
                    values=[[key, value]],
                )

            return UpdateSummaryResult(
                success=True,
                project=project,
                updated_fields=updated_fields,
                message=f"サマリシートを更新しました。更新項目: {', '.join(updated_fields)}",
            )

        except Exception as e:
            logger.error(f"Failed to update summary: {e}")
            return UpdateSummaryResult(
                success=False,
                project=project,
                message=f"サマリシートの更新に失敗しました: {e}",
            )

    def _get_recommended_docs(
        self,
        project: str,
        current_phase: str,
        current_task: str,
    ) -> list[DocReference]:
        """Get recommended documents based on current state.
        
        Args:
            project: Project ID
            current_phase: Current phase
            current_task: Current task
            
        Returns:
            List of recommended DocReference
        """
        recommended = []
        
        # Build phase-task identifier
        phase_task = ""
        if current_phase and current_task:
            # Extract phase number and task number
            # e.g., "Phase 4", "T01" -> "P4-T01"
            phase_num = "".join(c for c in current_phase if c.isdigit())
            task_num = current_task.split(":")[0].strip() if ":" in current_task else current_task
            if phase_num and task_num:
                phase_task = f"P{phase_num}-{task_num}"
        
        # Search catalog for relevant documents
        if phase_task:
            result = self.rag.search_catalog(
                query=phase_task,
                project=project,
                phase_task=phase_task,
                n_results=5,
            )
            
            if result.success:
                for doc in result.documents:
                    meta = doc.metadata
                    recommended.append(DocReference(
                        name=meta.get("name", ""),
                        doc_id=meta.get("doc_id", ""),
                        reason=f"現在タスク ({phase_task}) の関連ドキュメント",
                    ))
        
        # Also search by current task name
        if current_task and len(recommended) < 5:
            task_name = current_task.split(":")[-1].strip() if ":" in current_task else current_task
            
            result = self.rag.search_catalog(
                query=task_name,
                project=project,
                n_results=5 - len(recommended),
            )
            
            if result.success:
                existing_ids = {d.doc_id for d in recommended}
                for doc in result.documents:
                    meta = doc.metadata
                    doc_id = meta.get("doc_id", "")
                    if doc_id not in existing_ids:
                        recommended.append(DocReference(
                            name=meta.get("name", ""),
                            doc_id=doc_id,
                            reason=f"'{task_name}' に関連",
                        ))
        
        return recommended

    def _format_duration(self, duration: timedelta) -> str:
        """Format duration as human-readable string.
        
        Args:
            duration: Time duration
            
        Returns:
            Formatted string
        """
        total_seconds = int(duration.total_seconds())
        
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        parts = []
        if hours > 0:
            parts.append(f"{hours}時間")
        if minutes > 0:
            parts.append(f"{minutes}分")
        if seconds > 0 or not parts:
            parts.append(f"{seconds}秒")
        
        return "".join(parts)

    @property
    def is_session_active(self) -> bool:
        """Check if a session is currently active."""
        return self._session_start is not None

    @property
    def current_session_duration(self) -> Optional[timedelta]:
        """Get current session duration."""
        if self._session_start:
            return datetime.now() - self._session_start
        return None
