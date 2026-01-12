"""Project management tools for Spirrow-Prismind."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
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
    UpdateProjectResult,
)

logger = logging.getLogger(__name__)


class ProjectTools:
    """Tools for managing projects."""

    def __init__(
        self,
        rag_client: RAGClient,
        memory_client: MemoryClient,
        sheets_client: GoogleSheetsClient,
        drive_client: GoogleDriveClient,
        default_user: str = "default",
    ):
        """Initialize project tools.
        
        Args:
            rag_client: RAG client for project config storage
            memory_client: Memory client for current project
            sheets_client: Google Sheets client
            drive_client: Google Drive client
            default_user: Default user ID
        """
        self.rag = rag_client
        self.memory = memory_client
        self.sheets = sheets_client
        self.drive = drive_client
        self.default_user = default_user

    def setup_project(
        self,
        project: str,
        name: str,
        spreadsheet_id: str,
        root_folder_id: str,
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
            spreadsheet_id: Google Sheets ID
            root_folder_id: Google Drive root folder ID
            description: Project description
            create_sheets: Whether to create sheets automatically
            create_folders: Whether to create folders automatically
            force: Skip confirmation and force creation
            similarity_threshold: Similarity threshold for duplicate check
            user: User ID (uses default if None)
            
        Returns:
            SetupProjectResult
        """
        user = user or self.default_user
        
        # Step 1: Check for ID duplicate
        existing = self.rag.get_project_config(project)
        if existing:
            return SetupProjectResult(
                success=False,
                project_id=project,
                duplicate_id=True,
                message=f"プロジェクト '{project}' は既に存在します。"
                        f"update_project で設定を更新するか、別のIDで作成してください。",
            )
        
        # Step 2: Check for name duplicate
        duplicate_name = ""
        all_projects = self.rag.list_projects()
        for proj_doc in all_projects:
            if proj_doc.metadata.get("name") == name:
                duplicate_name = proj_doc.metadata.get("project_id", "")
                break
        
        # Step 3: Search for similar projects
        similar_projects: list[SimilarProject] = []
        if description or name:
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
        
        # Step 4: Check if confirmation is needed
        if not force and (duplicate_name or similar_projects):
            result = SetupProjectResult(
                success=False,
                project_id=project,
                name=name,
                requires_confirmation=True,
                duplicate_name=duplicate_name,
                similar_projects=similar_projects,
            )
            
            # Build message
            messages = []
            if duplicate_name:
                messages.append(f"⚠️ 同名のプロジェクト '{duplicate_name}' が存在します。")
            
            if similar_projects:
                messages.append("📋 類似のプロジェクトが見つかりました:")
                for sp in similar_projects:
                    messages.append(f"  - {sp.project_id} (類似度: {sp.similarity_percent}%): {sp.name}")
            
            messages.append("\n新規プロジェクトとして作成しますか？")
            result.message = "\n".join(messages)
            
            return result
        
        # Step 5: Create project config
        config = ProjectConfig(
            project_id=project,
            name=name,
            description=description,
            spreadsheet_id=spreadsheet_id,
            root_folder_id=root_folder_id,
        )
        
        # Save to RAG
        rag_result = self.rag.save_project_config(
            project_id=project,
            name=name,
            description=description,
            config_data={
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
            },
        )
        
        if not rag_result.success:
            return SetupProjectResult(
                success=False,
                project_id=project,
                message=f"プロジェクト設定の保存に失敗しました: {rag_result.message}",
            )
        
        sheets_created: list[str] = []
        folders_created: list[str] = []
        
        # Step 6: Create sheets if requested
        if create_sheets:
            try:
                sheet_names = [
                    config.sheets.summary,
                    config.sheets.progress,
                    config.sheets.catalog,
                ]
                
                for sheet_name in sheet_names:
                    # Check if sheet exists, create if not
                    try:
                        self.sheets.create_sheet(spreadsheet_id, sheet_name)
                        sheets_created.append(sheet_name)
                    except Exception as e:
                        # Sheet might already exist
                        logger.debug(f"Sheet '{sheet_name}' might already exist: {e}")
                
            except Exception as e:
                logger.error(f"Failed to create sheets: {e}")
        
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
        
        # Step 8: Set as current project in Memory
        self.memory.set_current_project(user, project)
        
        return SetupProjectResult(
            success=True,
            project_id=project,
            name=name,
            sheets_created=sheets_created,
            folders_created=folders_created,
            message=f"プロジェクト '{name}' をセットアップしました。",
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
        user = user or self.default_user
        
        # Get project config from RAG
        config_doc = self.rag.get_project_config(project)
        
        if not config_doc:
            return SwitchProjectResult(
                success=False,
                project_id=project,
                message=f"プロジェクト '{project}' が見つかりません。",
            )
        
        # Update current project in Memory
        result = self.memory.set_current_project(user, project)
        
        if not result.success:
            return SwitchProjectResult(
                success=False,
                project_id=project,
                message=f"プロジェクトの切り替えに失敗しました: {result.message}",
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
        user = user or self.default_user
        
        # Get all projects from RAG
        project_docs = self.rag.list_projects()
        
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
        
        # Get current project from Memory
        current = self.memory.get_current_project(user)
        current_project = current.project_id if current else ""
        
        return ListProjectsResult(
            success=True,
            projects=projects,
            current_project=current_project,
            message=f"{len(projects)} 件のプロジェクトが登録されています。",
        )

    def update_project(
        self,
        project: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        spreadsheet_id: Optional[str] = None,
        root_folder_id: Optional[str] = None,
    ) -> UpdateProjectResult:
        """Update project settings.
        
        Args:
            project: Project identifier
            name: New display name (None to keep)
            description: New description (None to keep)
            spreadsheet_id: New Sheets ID (None to keep)
            root_folder_id: New Drive folder ID (None to keep)
            
        Returns:
            UpdateProjectResult
        """
        # Get existing config
        config_doc = self.rag.get_project_config(project)
        
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
        }
        
        result = self.rag.save_project_config(
            project_id=project,
            name=new_name,
            description=new_description,
            config_data=config_data,
        )
        
        if not result.success:
            return UpdateProjectResult(
                success=False,
                project_id=project,
                message=f"プロジェクト設定の更新に失敗しました: {result.message}",
            )
        
        return UpdateProjectResult(
            success=True,
            project_id=project,
            updated_fields=updated_fields,
            message=f"プロジェクト '{new_name}' を更新しました: {', '.join(updated_fields)}",
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
        config_doc = self.rag.get_project_config(project)
        
        if not config_doc:
            return DeleteProjectResult(
                success=False,
                project_id=project,
                message=f"プロジェクト '{project}' が見つかりません。",
            )
        
        # Delete from RAG
        result = self.rag.delete_project_config(project)
        
        if not result.success:
            return DeleteProjectResult(
                success=False,
                project_id=project,
                message=f"プロジェクト設定の削除に失敗しました: {result.message}",
            )
        
        # Also delete catalog entries for this project
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
        user = user or self.default_user
        
        # If no project specified, get current
        if project is None:
            current = self.memory.get_current_project(user)
            if not current:
                return None
            project = current.project_id
        
        # Get from RAG
        config_doc = self.rag.get_project_config(project)
        
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
        user = user or self.default_user
        
        current = self.memory.get_current_project(user)
        return current.project_id if current else None
