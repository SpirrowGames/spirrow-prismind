"""Project management tools for Spirrow-Prismind."""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..integrations import (
    GoogleDriveClient,
    GoogleSheetsClient,
    MemoryClient,
    RAGClient,
    RAGDocument,
)
from ..models import (
    DeleteProjectResult,
    ListProjectsResult,
    ProjectConfig,
    ProjectSummary,
    SetupProjectResult,
    SimilarProject,
    SwitchProjectResult,
    SyncProjectsResult,
    UpdateProjectResult,
    create_catalog_template,
    create_progress_template,
    create_summary_template,
)

logger = logging.getLogger(__name__)


class ProjectTools:
    """Tools for managing projects."""

    # File-based fallback storage when RAG/Memory are unavailable
    _fallback_file: Optional[Path] = None
    _fallback_projects: dict[str, dict] = {}
    _fallback_current_project: dict[str, str] = {}  # user -> project_id

    def __init__(
        self,
        rag_client: RAGClient,
        memory_client: MemoryClient,
        sheets_client: GoogleSheetsClient,
        drive_client: GoogleDriveClient,
        user_name: str = "default",
        projects_folder_id: str = "",
    ):
        """Initialize project tools.

        Args:
            rag_client: RAG client for project config storage
            memory_client: Memory client for current project
            sheets_client: Google Sheets client
            drive_client: Google Drive client
            user_name: Default user ID
            projects_folder_id: Root folder ID for all projects (from config)
        """
        self.rag = rag_client
        self.memory = memory_client
        self.sheets = sheets_client
        self.drive = drive_client
        self.user_name = user_name
        self.projects_folder_id = projects_folder_id

        # Initialize fallback storage file path
        self._init_fallback_storage()

        # Log service availability (RAG/Memory are optional)
        if not self.rag.is_available:
            logger.info(f"RAG server unavailable (optional) - using local storage: {self._fallback_file}")
        if not self.memory.is_available:
            logger.info("Memory server unavailable (optional) - using local storage for current project")

    def _init_fallback_storage(self):
        """Initialize file-based fallback storage."""
        # Determine fallback file location
        config_path = os.environ.get("PRISMIND_CONFIG", "config.toml")
        config_dir = Path(config_path).parent
        self._fallback_file = config_dir / ".prismind_projects.json"

        # Load existing data if available
        self._load_fallback_data()

    def _load_fallback_data(self):
        """Load fallback data from file."""
        if self._fallback_file and self._fallback_file.exists():
            try:
                with open(self._fallback_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    ProjectTools._fallback_projects = data.get("projects", {})
                    ProjectTools._fallback_current_project = data.get("current_project", {})
                    logger.info(f"Loaded {len(ProjectTools._fallback_projects)} projects from fallback storage")
            except Exception as e:
                logger.error(f"Failed to load fallback storage: {e}")
                ProjectTools._fallback_projects = {}
                ProjectTools._fallback_current_project = {}

    def _save_fallback_data(self):
        """Save fallback data to file."""
        if self._fallback_file:
            try:
                data = {
                    "projects": ProjectTools._fallback_projects,
                    "current_project": ProjectTools._fallback_current_project,
                }
                with open(self._fallback_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.debug(f"Saved fallback data to {self._fallback_file}")
            except Exception as e:
                logger.error(f"Failed to save fallback storage: {e}")

    # ===== Fallback Storage Helpers =====

    def _get_project_config_with_fallback(self, project: str) -> Optional[RAGDocument]:
        """Get project config from RAG or fallback storage.

        RAG is optional - if RAG fails, falls back to file storage.
        """
        # Try RAG first if available
        if self.rag.is_available:
            try:
                result = self.rag.get_project_config(project)
                if result:
                    return result
                # Not found in RAG, try fallback
            except Exception as e:
                logger.warning(f"RAG get failed for project '{project}': {e}. Trying fallback storage.")

        # Fallback to file storage
        data = ProjectTools._fallback_projects.get(project)
        if data:
            return RAGDocument(
                doc_id=f"project:{project}",
                content=f"{data.get('name', '')} - {data.get('description', '')}",
                metadata=data,
            )
        return None

    def _save_project_config_with_fallback(
        self,
        project_id: str,
        name: str,
        description: str,
        config_data: dict,
    ) -> tuple[bool, str]:
        """Save project config to RAG or fallback storage.

        RAG is optional - if RAG fails for any reason, falls back to file storage.

        Returns:
            Tuple of (success, warning_message). warning_message may contain
            info about fallback usage even on success.
        """
        rag_error: Optional[str] = None

        # Try RAG first if available
        if self.rag.is_available:
            try:
                result = self.rag.save_project_config(
                    project_id=project_id,
                    name=name,
                    description=description,
                    config_data=config_data,
                )
                if result.success:
                    return True, ""
                else:
                    rag_error = result.message
                    logger.warning(
                        f"RAG save failed for project '{project_id}': {result.message}. "
                        "Falling back to file storage."
                    )
            except Exception as e:
                rag_error = str(e)
                logger.warning(
                    f"RAG save exception for project '{project_id}': {e}. "
                    "Falling back to file storage."
                )

        # Fallback to file storage (either RAG unavailable or RAG failed)
        ProjectTools._fallback_projects[project_id] = {
            "project_id": project_id,
            "name": name,
            "description": description,
            "updated_at": datetime.now().isoformat(),
            **config_data,
        }
        self._save_fallback_data()
        logger.info(f"Project '{project_id}' saved to file-based fallback storage")

        # Return success with warning if RAG failed
        if rag_error:
            return True, f"RAGサーバーへの保存に失敗しましたが、ローカルストレージに保存しました（RAGエラー: {rag_error}）"
        elif not self.rag.is_available:
            return True, "RAGサーバーが利用できないため、ローカルストレージに保存しました"
        return True, ""

    def _list_projects_with_fallback(self) -> list[RAGDocument]:
        """List projects from RAG and fallback storage.

        Merges results from both sources, preferring RAG data when available.
        RAG is optional - if RAG fails, returns only fallback storage projects.
        """
        docs: list[RAGDocument] = []
        seen_ids: set[str] = set()

        # Try RAG first if available
        if self.rag.is_available:
            try:
                rag_docs = self.rag.list_projects()
                for doc in rag_docs:
                    project_id = doc.metadata.get("project_id", "")
                    if project_id:
                        seen_ids.add(project_id)
                    docs.append(doc)
            except Exception as e:
                logger.warning(f"RAG list_projects failed: {e}. Using fallback storage only.")

        # Add projects from fallback that aren't in RAG
        for project_id, data in ProjectTools._fallback_projects.items():
            if project_id not in seen_ids:
                docs.append(RAGDocument(
                    doc_id=f"project:{project_id}",
                    content=f"{data.get('name', '')} - {data.get('description', '')}",
                    metadata=data,
                ))

        return docs

    def _delete_project_config_with_fallback(self, project: str) -> bool:
        """Delete project config from RAG and fallback storage.

        Attempts to delete from both sources. RAG errors are logged but don't prevent
        fallback deletion.
        """
        deleted = False

        # Try RAG if available
        if self.rag.is_available:
            try:
                result = self.rag.delete_project_config(project)
                if result.success:
                    deleted = True
            except Exception as e:
                logger.warning(f"RAG delete failed for project '{project}': {e}")

        # Also delete from fallback storage
        if project in ProjectTools._fallback_projects:
            del ProjectTools._fallback_projects[project]
            self._save_fallback_data()
            deleted = True

        return deleted

    def _get_current_project_with_fallback(self, user: str) -> Optional[str]:
        """Get current project from Memory or fallback storage.

        Memory server is optional - falls back to file storage on errors.
        """
        # Try Memory server first if available
        if self.memory.is_available:
            try:
                current = self.memory.get_current_project(user)
                if current and current.project_id:
                    return current.project_id
            except Exception as e:
                logger.warning(f"Memory get_current_project failed: {e}. Trying fallback storage.")

        # Fallback to file storage
        return ProjectTools._fallback_current_project.get(user)

    def _set_current_project_with_fallback(self, user: str, project_id: str) -> bool:
        """Set current project in Memory and fallback storage.

        Memory server is optional - always saves to fallback as backup.
        """
        success = True

        # Try Memory server if available
        if self.memory.is_available:
            try:
                result = self.memory.set_current_project(user, project_id)
                if not result.success:
                    logger.warning(f"Memory set_current_project failed: {result.message}")
            except Exception as e:
                logger.warning(f"Memory set_current_project exception: {e}")

        # Always save to fallback storage as backup
        ProjectTools._fallback_current_project[user] = project_id
        self._save_fallback_data()

        return success

    # ===== Main Methods =====

    def setup_project(
        self,
        project: str,
        name: str,
        spreadsheet_id: Optional[str] = None,
        root_folder_id: Optional[str] = None,
        description: str = "",
        create_sheets: bool = True,
        create_folders: bool = True,
        force: bool = False,
        similarity_threshold: float = 0.7,
        user: Optional[str] = None,
    ) -> SetupProjectResult:
        """Setup a new project.

        Args:
            project: Project identifier (alphanumeric)
            name: Display name
            spreadsheet_id: Google Sheets ID (None to auto-create)
            root_folder_id: Google Drive root folder ID (None to auto-create under projects_folder)
            description: Project description
            create_sheets: Whether to create sheets automatically
            create_folders: Whether to create folders automatically
            force: Skip confirmation and force creation
            similarity_threshold: Similarity threshold for duplicate check
            user: User ID (uses default if None)

        Returns:
            SetupProjectResult
        """
        user = user or self.user_name

        # Auto-creation mode: create project folder and spreadsheet
        auto_created_folder = False
        auto_created_spreadsheet = False

        if not root_folder_id and not spreadsheet_id:
            # Auto-create mode
            if not self.projects_folder_id:
                return SetupProjectResult(
                    success=False,
                    project_id=project,
                    message="プロジェクトの自動作成にはconfig.tomlのprojects_folder_idが必要です。"
                            "または、spreadsheet_idとroot_folder_idを直接指定してください。",
                )

            try:
                # Create project folder under projects_folder
                logger.info(f"Creating project folder '{name}' under projects folder")
                project_folder = self.drive.create_folder(name, self.projects_folder_id)
                root_folder_id = project_folder.file_id
                auto_created_folder = True

                # Create spreadsheet in project folder
                spreadsheet_name = f"{name}_Summary"
                logger.info(f"Creating spreadsheet '{spreadsheet_name}' in project folder")
                spreadsheet = self.drive.create_spreadsheet(spreadsheet_name, root_folder_id)
                spreadsheet_id = spreadsheet.file_id
                auto_created_spreadsheet = True

            except Exception as e:
                logger.error(f"Failed to auto-create project resources: {e}")
                return SetupProjectResult(
                    success=False,
                    project_id=project,
                    message=f"プロジェクトリソースの自動作成に失敗しました: {e}",
                )

        # Validate required IDs
        if not spreadsheet_id or not root_folder_id:
            return SetupProjectResult(
                success=False,
                project_id=project,
                message="spreadsheet_idとroot_folder_idの両方が必要です。",
            )

        # Step 1: Check for ID duplicate
        existing = self._get_project_config_with_fallback(project)
        if existing:
            return SetupProjectResult(
                success=False,
                project_id=project,
                duplicate_id=True,
                message=f"プロジェクト '{project}' は既に存在します。"
                        f"update_project で設定を更新するか、別のIDで作成してください。",
            )

        # Step 2: Check for name duplicate (always blocked, regardless of force)
        duplicate_name = ""
        all_projects = self._list_projects_with_fallback()
        for proj_doc in all_projects:
            if proj_doc.metadata.get("name") == name:
                duplicate_name = proj_doc.metadata.get("project_id", "")
                break

        if duplicate_name:
            return SetupProjectResult(
                success=False,
                project_id=project,
                duplicate_name=duplicate_name,
                message=f"同名のプロジェクト '{name}' が既に存在します（ID: {duplicate_name}）。"
                        f"別の名前を指定するか、既存プロジェクトを使用してください。",
            )

        # Step 3: Search for similar projects (only if RAG is available)
        similar_projects: list[SimilarProject] = []
        if self.rag.is_available and (description or name):
            similar_docs = self.rag.find_similar_projects(
                name=name,
                description=description,
                threshold=similarity_threshold,
                exclude_project_id=project,
            )

            for doc in similar_docs:
                similar_projects.append(SimilarProject(
                    project_id=doc.metadata.get("project_id", ""),
                    name=doc.metadata.get("name", ""),
                    description=doc.metadata.get("description", ""),
                    similarity=doc.score,
                ))

        # Step 4: Check if confirmation is needed (only for similar projects)
        if not force and similar_projects:
            messages = ["📋 類似のプロジェクトが見つかりました:"]
            for sp in similar_projects:
                messages.append(f"  - {sp.project_id} (類似度: {sp.similarity_percent}%): {sp.name}")
            messages.append("\n新規プロジェクトとして作成する場合は force=True を指定してください。")

            return SetupProjectResult(
                success=False,
                project_id=project,
                name=name,
                requires_confirmation=True,
                similar_projects=similar_projects,
                message="\n".join(messages),
            )
        
        # Step 5: Create project config
        config = ProjectConfig(
            project_id=project,
            name=name,
            description=description,
            spreadsheet_id=spreadsheet_id,
            root_folder_id=root_folder_id,
        )
        
        # Save project config
        config_data = {
            "spreadsheet_id": spreadsheet_id,
            "root_folder_id": root_folder_id,
            "sheets": {
                "summary": config.sheets.summary,
                "progress": config.sheets.progress,
                "catalog": config.sheets.catalog,
            },
            "drive": {
                "design_folder": config.drive.design_folder,
                "procedure_folder": config.drive.procedure_folder,
            },
            "options": {
                "auto_sync_catalog": config.options.auto_sync_catalog,
                "auto_create_folders": config.options.auto_create_folders,
            },
            "created_at": datetime.now().isoformat(),
        }

        save_success, save_warning = self._save_project_config_with_fallback(
            project_id=project,
            name=name,
            description=description,
            config_data=config_data,
        )

        if not save_success:
            # This shouldn't happen with the new fallback logic, but keep for safety
            return SetupProjectResult(
                success=False,
                project_id=project,
                message=f"プロジェクト設定の保存に失敗しました: {save_warning}",
            )
        
        sheets_created: list[str] = []
        folders_created: list[str] = []

        # Step 6: Create sheets with templates if requested
        if create_sheets:
            # Initialize sheets (rename default sheet + create new ones)
            try:
                sheets_created = self.sheets.initialize_project_sheets(
                    spreadsheet_id=spreadsheet_id,
                    summary_name=config.sheets.summary,
                    progress_name=config.sheets.progress,
                    catalog_name=config.sheets.catalog,
                )
                logger.info(f"Initialized sheets: {sheets_created}")
            except Exception as e:
                logger.error(f"Failed to initialize sheets: {e}")
                # Continue anyway - sheets might already exist

            # Write Summary template
            try:
                summary_data = create_summary_template(
                    project_name=name,
                    description=description,
                    created_by=user,
                )
                self.sheets.update_sheet_values(
                    spreadsheet_id=spreadsheet_id,
                    range_name=f"{config.sheets.summary}!A1",
                    values=summary_data,
                )
                logger.info(f"Wrote Summary template to {config.sheets.summary}")
            except Exception as e:
                logger.error(f"Failed to write Summary template: {e}")

            # Write Progress template (headers + initial task)
            try:
                progress_data = create_progress_template()
                self.sheets.update_sheet_values(
                    spreadsheet_id=spreadsheet_id,
                    range_name=f"{config.sheets.progress}!A1",
                    values=progress_data,
                )
                logger.info(f"Wrote Progress template to {config.sheets.progress}")
            except Exception as e:
                logger.error(f"Failed to write Progress template: {e}")

            # Write Catalog template (headers only)
            try:
                catalog_data = create_catalog_template()
                self.sheets.update_sheet_values(
                    spreadsheet_id=spreadsheet_id,
                    range_name=f"{config.sheets.catalog}!A1",
                    values=catalog_data,
                )
                logger.info(f"Wrote Catalog template to {config.sheets.catalog}")
            except Exception as e:
                logger.error(f"Failed to write Catalog template: {e}")
        
        # Step 7: Create folders if requested
        if create_folders:
            try:
                folder_names = [
                    config.drive.design_folder,
                    config.drive.procedure_folder,
                ]
                
                created_folders = self.drive.create_folder_structure(
                    root_folder_id,
                    folder_names,
                )
                
                folders_created = list(created_folders.keys())
                
            except Exception as e:
                logger.error(f"Failed to create folders: {e}")
        
        # Step 8: Set as current project
        self._set_current_project_with_fallback(user, project)

        # Build success message
        msg_parts = [f"プロジェクト '{name}' をセットアップしました。"]
        if auto_created_folder:
            msg_parts.append(f"フォルダを自動作成しました。")
        if auto_created_spreadsheet:
            msg_parts.append(f"スプレッドシートを自動作成しました。")
        if save_warning:
            msg_parts.append(f"⚠️ {save_warning}")

        return SetupProjectResult(
            success=True,
            project_id=project,
            name=name,
            spreadsheet_id=spreadsheet_id,
            root_folder_id=root_folder_id,
            sheets_created=sheets_created,
            folders_created=folders_created,
            message=" ".join(msg_parts),
        )

    def switch_project(
        self,
        project: str,
        user: Optional[str] = None,
    ) -> SwitchProjectResult:
        """Switch to a different project.
        
        Args:
            project: Project identifier
            user: User ID (uses default if None)
            
        Returns:
            SwitchProjectResult
        """
        user = user or self.user_name

        # Get project config
        config_doc = self._get_project_config_with_fallback(project)

        if not config_doc:
            return SwitchProjectResult(
                success=False,
                project_id=project,
                message=f"プロジェクト '{project}' が見つかりません。",
            )

        # Update current project
        success = self._set_current_project_with_fallback(user, project)

        if not success:
            return SwitchProjectResult(
                success=False,
                project_id=project,
                message="プロジェクトの切り替えに失敗しました。",
            )

        name = config_doc.metadata.get("name", project)

        return SwitchProjectResult(
            success=True,
            project_id=project,
            name=name,
            message=f"プロジェクト '{name}' に切り替えました。",
        )

    def list_projects(
        self,
        user: Optional[str] = None,
    ) -> ListProjectsResult:
        """List all registered projects.
        
        Args:
            user: User ID (uses default if None)
            
        Returns:
            ListProjectsResult
        """
        user = user or self.user_name

        # Get all projects
        project_docs = self._list_projects_with_fallback()

        projects = []
        for doc in project_docs:
            meta = doc.metadata

            updated_at_str = meta.get("updated_at", "")
            if updated_at_str:
                try:
                    updated_at = datetime.fromisoformat(updated_at_str)
                except ValueError:
                    updated_at = datetime.now()
            else:
                updated_at = datetime.now()

            projects.append(ProjectSummary(
                project_id=meta.get("project_id", ""),
                name=meta.get("name", ""),
                description=meta.get("description", ""),
                updated_at=updated_at,
            ))

        # Sort by updated_at descending
        projects.sort(key=lambda p: p.updated_at, reverse=True)

        # Get current project
        current_project = self._get_current_project_with_fallback(user) or ""

        # Add note if using fallback storage
        storage_note = ""
        if not self.rag.is_available:
            storage_note = " (ローカルストレージ使用中 - 類似プロジェクト検索機能は制限されます)"

        return ListProjectsResult(
            success=True,
            projects=projects,
            current_project=current_project,
            message=f"{len(projects)} 件のプロジェクトが登録されています。{storage_note}",
        )

    def update_project(
        self,
        project: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        spreadsheet_id: Optional[str] = None,
        root_folder_id: Optional[str] = None,
        status: Optional[str] = None,
        categories: Optional[list[str]] = None,
        phases: Optional[list[str]] = None,
        template: Optional[str] = None,
    ) -> UpdateProjectResult:
        """Update project settings.

        Args:
            project: Project identifier
            name: New display name (None to keep)
            description: New description (None to keep)
            spreadsheet_id: New Sheets ID (None to keep)
            root_folder_id: New Drive folder ID (None to keep)
            status: Project status (active, archived, etc.)
            categories: Project categories list
            phases: Project phases list
            template: Template type (game, mcp-server, web-app, etc.)

        Returns:
            UpdateProjectResult
        """
        # Get existing config
        config_doc = self._get_project_config_with_fallback(project)

        if not config_doc:
            return UpdateProjectResult(
                success=False,
                project_id=project,
                message=f"プロジェクト '{project}' が見つかりません。",
            )

        # Build updated config
        meta = config_doc.metadata
        updated_fields = []

        new_name = name if name is not None else meta.get("name", "")
        if name is not None and name != meta.get("name"):
            updated_fields.append("name")

        new_description = description if description is not None else meta.get("description", "")
        if description is not None and description != meta.get("description"):
            updated_fields.append("description")

        new_spreadsheet_id = spreadsheet_id if spreadsheet_id is not None else meta.get("spreadsheet_id", "")
        if spreadsheet_id is not None and spreadsheet_id != meta.get("spreadsheet_id"):
            updated_fields.append("spreadsheet_id")

        new_root_folder_id = root_folder_id if root_folder_id is not None else meta.get("root_folder_id", "")
        if root_folder_id is not None and root_folder_id != meta.get("root_folder_id"):
            updated_fields.append("root_folder_id")

        # Extended fields for Magickit
        new_status = status if status is not None else meta.get("status", "active")
        if status is not None and status != meta.get("status"):
            updated_fields.append("status")

        new_categories = categories if categories is not None else meta.get("categories", [])
        if categories is not None and categories != meta.get("categories"):
            updated_fields.append("categories")

        new_phases = phases if phases is not None else meta.get("phases", [])
        if phases is not None and phases != meta.get("phases"):
            updated_fields.append("phases")

        new_template = template if template is not None else meta.get("template", "")
        if template is not None and template != meta.get("template"):
            updated_fields.append("template")

        if not updated_fields:
            return UpdateProjectResult(
                success=True,
                project_id=project,
                updated_fields=[],
                message="更新する項目がありません。",
            )

        # Save updated config
        config_data = {
            "spreadsheet_id": new_spreadsheet_id,
            "root_folder_id": new_root_folder_id,
            "sheets": meta.get("sheets", {}),
            "drive": meta.get("drive", {}),
            "options": meta.get("options", {}),
            "created_at": meta.get("created_at", datetime.now().isoformat()),
            # Extended fields for Magickit
            "status": new_status,
            "categories": new_categories,
            "phases": new_phases,
            "template": new_template,
        }

        success, save_warning = self._save_project_config_with_fallback(
            project_id=project,
            name=new_name,
            description=new_description,
            config_data=config_data,
        )

        if not success:
            # This shouldn't happen with the new fallback logic, but keep for safety
            return UpdateProjectResult(
                success=False,
                project_id=project,
                message=f"プロジェクト設定の更新に失敗しました: {save_warning}",
            )

        msg = f"プロジェクト '{new_name}' を更新しました: {', '.join(updated_fields)}"
        if save_warning:
            msg += f" ⚠️ {save_warning}"

        return UpdateProjectResult(
            success=True,
            project_id=project,
            updated_fields=updated_fields,
            message=msg,
        )

    def delete_project(
        self,
        project: str,
        confirm: bool = False,
    ) -> DeleteProjectResult:
        """Delete project settings (not actual data).
        
        Args:
            project: Project identifier
            confirm: Confirmation flag (must be True)
            
        Returns:
            DeleteProjectResult
        """
        if not confirm:
            return DeleteProjectResult(
                success=False,
                project_id=project,
                message="削除を確認するには confirm=True を指定してください。"
                        "注意: これはプロジェクト設定のみを削除します。"
                        "Google Drive/Sheets のデータは残ります。",
            )

        # Check if project exists
        config_doc = self._get_project_config_with_fallback(project)

        if not config_doc:
            return DeleteProjectResult(
                success=False,
                project_id=project,
                message=f"プロジェクト '{project}' が見つかりません。",
            )

        # Delete project config
        success = self._delete_project_config_with_fallback(project)

        if not success:
            return DeleteProjectResult(
                success=False,
                project_id=project,
                message="プロジェクト設定の削除に失敗しました。",
            )

        # Also delete catalog entries for this project (only if RAG is available)
        deleted_catalog_count = 0
        if self.rag.is_available:
            deleted_catalog_count = self.rag.delete_catalog_entries_by_project(project)

        name = config_doc.metadata.get("name", project)

        return DeleteProjectResult(
            success=True,
            project_id=project,
            message=f"プロジェクト '{name}' の設定を削除しました。"
                    f"（目録エントリ {deleted_catalog_count} 件も削除）",
        )

    def get_project_config(
        self,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> Optional[ProjectConfig]:
        """Get project configuration.
        
        Args:
            project: Project identifier (None to use current)
            user: User ID (uses default if None)
            
        Returns:
            ProjectConfig if found, None otherwise
        """
        user = user or self.user_name

        # If no project specified, get current
        if project is None:
            project = self._get_current_project_with_fallback(user)
            if not project:
                return None

        # Get project config
        config_doc = self._get_project_config_with_fallback(project)

        if not config_doc:
            return None

        return ProjectConfig.from_rag_document({"metadata": config_doc.metadata})

    def get_current_project_id(
        self,
        user: Optional[str] = None,
    ) -> Optional[str]:
        """Get the current project ID.

        Args:
            user: User ID (uses default if None)

        Returns:
            Project ID if set, None otherwise
        """
        user = user or self.user_name
        return self._get_current_project_with_fallback(user)

    def sync_projects_from_drive(
        self,
        dry_run: bool = False,
    ) -> SyncProjectsResult:
        """Sync projects from Google Drive to RAG.

        Uses Google Drive (projects_folder_id) as the master source.
        - Folders in Drive that are not in RAG will be added
        - Projects in RAG that don't exist in Drive will be removed

        Args:
            dry_run: If True, only report differences without making changes

        Returns:
            SyncProjectsResult with added, removed, and unchanged project lists
        """
        if not self.projects_folder_id:
            return SyncProjectsResult(
                success=False,
                message="projects_folder_idが設定されていません。config.tomlで設定してください。",
            )

        errors = []

        # 1. Get folder list from Drive
        drive_projects: dict[str, dict] = {}
        try:
            contents = self.drive.list_folder_contents(self.projects_folder_id)
            for folder in contents.subfolders:
                # Search for spreadsheet in each folder
                spreadsheet = self._find_project_spreadsheet(folder.file_id)
                if spreadsheet:
                    drive_projects[folder.name] = {
                        "folder_id": folder.file_id,
                        "spreadsheet_id": spreadsheet.file_id,
                        "name": folder.name,
                    }
                else:
                    logger.debug(
                        f"Skipping folder '{folder.name}': no spreadsheet found"
                    )
        except Exception as e:
            return SyncProjectsResult(
                success=False,
                errors=[f"Google Drive取得エラー: {e}"],
                message="Google Driveからフォルダ一覧を取得できませんでした。",
            )

        # 2. Get existing projects from RAG
        rag_projects: dict[str, RAGDocument] = {}
        if self.rag.is_available:
            try:
                rag_docs = self.rag.list_projects()
                for doc in rag_docs:
                    project_id = doc.metadata.get("project_id", "")
                    if project_id:
                        rag_projects[project_id] = doc
            except Exception as e:
                errors.append(f"RAG取得警告: {e}")

        # Also include fallback storage
        for project_id, data in ProjectTools._fallback_projects.items():
            if project_id not in rag_projects:
                rag_projects[project_id] = RAGDocument(
                    doc_id=f"project:{project_id}",
                    content=data.get("name", ""),
                    metadata=data,
                )

        # 3. Calculate differences
        drive_ids = set(drive_projects.keys())
        rag_ids = set(rag_projects.keys())

        to_add = sorted(drive_ids - rag_ids)
        to_remove = sorted(rag_ids - drive_ids)
        unchanged = sorted(drive_ids & rag_ids)

        if dry_run:
            # Report only, no changes
            message_parts = []
            if to_add:
                message_parts.append(f"追加予定: {len(to_add)}件 ({', '.join(to_add)})")
            if to_remove:
                message_parts.append(f"削除予定: {len(to_remove)}件 ({', '.join(to_remove)})")
            if unchanged:
                message_parts.append(f"変更なし: {len(unchanged)}件")
            if not message_parts:
                message_parts.append("同期対象がありません")

            return SyncProjectsResult(
                success=True,
                added=to_add,
                removed=to_remove,
                unchanged=unchanged,
                errors=errors,
                message="[Dry Run] " + "; ".join(message_parts),
            )

        # 4. Add new projects
        added = []
        for project_id in to_add:
            info = drive_projects[project_id]
            try:
                success, warning = self._save_project_config_with_fallback(
                    project_id=project_id,
                    name=info["name"],
                    description="",
                    config_data={
                        "spreadsheet_id": info["spreadsheet_id"],
                        "root_folder_id": info["folder_id"],
                    },
                )
                if success:
                    added.append(project_id)
                    logger.info(f"Synced project from Drive: {project_id}")
                else:
                    errors.append(f"追加失敗 ({project_id}): {warning}")
            except Exception as e:
                errors.append(f"追加エラー ({project_id}): {e}")

        # 5. Remove projects not in Drive
        removed = []
        for project_id in to_remove:
            try:
                # Remove from RAG
                if self.rag.is_available:
                    self.rag.delete_project_config(project_id)

                # Remove from fallback storage
                if project_id in ProjectTools._fallback_projects:
                    del ProjectTools._fallback_projects[project_id]
                    self._save_fallback_data()

                removed.append(project_id)
                logger.info(f"Removed project not in Drive: {project_id}")
            except Exception as e:
                errors.append(f"削除エラー ({project_id}): {e}")

        # Build result message
        message_parts = []
        if added:
            message_parts.append(f"追加: {len(added)}件")
        if removed:
            message_parts.append(f"削除: {len(removed)}件")
        if unchanged:
            message_parts.append(f"変更なし: {len(unchanged)}件")
        if errors:
            message_parts.append(f"エラー: {len(errors)}件")

        return SyncProjectsResult(
            success=True,
            added=added,
            removed=removed,
            unchanged=unchanged,
            errors=errors,
            message="; ".join(message_parts) if message_parts else "同期完了",
        )

    def _find_project_spreadsheet(self, folder_id: str) -> Optional[any]:
        """Find the project management spreadsheet in a folder.

        Args:
            folder_id: Google Drive folder ID

        Returns:
            FileInfo of the spreadsheet if found, None otherwise
        """
        try:
            contents = self.drive.list_folder_contents(folder_id)
            # Look for a spreadsheet (Google Sheets mime type)
            for file in contents.files:
                if file.mime_type == "application/vnd.google-apps.spreadsheet":
                    return file
            return None
        except Exception as e:
            logger.warning(f"Failed to search folder {folder_id}: {e}")
            return None
