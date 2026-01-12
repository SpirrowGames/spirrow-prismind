"""Project configuration model (stored in RAG)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SheetsConfig:
    """Google Sheets configuration for a project."""
    summary: str = "サマリ"
    progress: str = "進捗"
    catalog: str = "目録"


@dataclass
class DriveConfig:
    """Google Drive folder configuration for a project."""
    design_folder: str = "設計書"
    procedure_folder: str = "実装手順書"


@dataclass
class DocsConfig:
    """Google Docs configuration for a project."""
    template_folder_id: str = ""
    default_template: str = ""


@dataclass
class ProjectOptions:
    """Project options."""
    auto_sync_catalog: bool = True
    auto_create_folders: bool = True


@dataclass
class ProjectConfig:
    """Project configuration stored in RAG."""
    
    # Required fields
    project_id: str
    name: str
    spreadsheet_id: str
    root_folder_id: str
    
    # Optional fields
    description: str = ""
    sheets: SheetsConfig = field(default_factory=SheetsConfig)
    drive: DriveConfig = field(default_factory=DriveConfig)
    docs: DocsConfig = field(default_factory=DocsConfig)
    options: ProjectOptions = field(default_factory=ProjectOptions)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_rag_document(self) -> dict:
        """Convert to RAG document format for storage."""
        return {
            "id": f"project:{self.project_id}",
            "content": f"{self.name} - {self.description}",
            "metadata": {
                "type": "project_config",
                "project_id": self.project_id,
                "name": self.name,
                "description": self.description,
                "spreadsheet_id": self.spreadsheet_id,
                "root_folder_id": self.root_folder_id,
                "sheets": {
                    "summary": self.sheets.summary,
                    "progress": self.sheets.progress,
                    "catalog": self.sheets.catalog,
                },
                "drive": {
                    "design_folder": self.drive.design_folder,
                    "procedure_folder": self.drive.procedure_folder,
                },
                "docs": {
                    "template_folder_id": self.docs.template_folder_id,
                    "default_template": self.docs.default_template,
                },
                "options": {
                    "auto_sync_catalog": self.options.auto_sync_catalog,
                    "auto_create_folders": self.options.auto_create_folders,
                },
                "created_at": self.created_at.isoformat(),
                "updated_at": self.updated_at.isoformat(),
            },
        }

    @classmethod
    def from_rag_document(cls, doc: dict) -> "ProjectConfig":
        """Create from RAG document."""
        metadata = doc.get("metadata", {})
        
        sheets_data = metadata.get("sheets", {})
        drive_data = metadata.get("drive", {})
        docs_data = metadata.get("docs", {})
        options_data = metadata.get("options", {})
        
        created_at = metadata.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        else:
            created_at = datetime.now()
            
        updated_at = metadata.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        else:
            updated_at = datetime.now()

        return cls(
            project_id=metadata.get("project_id", ""),
            name=metadata.get("name", ""),
            description=metadata.get("description", ""),
            spreadsheet_id=metadata.get("spreadsheet_id", ""),
            root_folder_id=metadata.get("root_folder_id", ""),
            sheets=SheetsConfig(
                summary=sheets_data.get("summary", "サマリ"),
                progress=sheets_data.get("progress", "進捗"),
                catalog=sheets_data.get("catalog", "目録"),
            ),
            drive=DriveConfig(
                design_folder=drive_data.get("design_folder", "設計書"),
                procedure_folder=drive_data.get("procedure_folder", "実装手順書"),
            ),
            docs=DocsConfig(
                template_folder_id=docs_data.get("template_folder_id", ""),
                default_template=docs_data.get("default_template", ""),
            ),
            options=ProjectOptions(
                auto_sync_catalog=options_data.get("auto_sync_catalog", True),
                auto_create_folders=options_data.get("auto_create_folders", True),
            ),
            created_at=created_at,
            updated_at=updated_at,
        )


@dataclass
class ProjectSummary:
    """Summary of a project for listing."""
    project_id: str
    name: str
    description: str
    updated_at: datetime


@dataclass
class SimilarProject:
    """Similar project found during setup."""
    project_id: str
    name: str
    description: str
    similarity: float  # 0.0 - 1.0
    
    @property
    def similarity_percent(self) -> int:
        """Get similarity as percentage."""
        return int(self.similarity * 100)


@dataclass
class SetupProjectResult:
    """Result of setting up a project."""
    success: bool
    project_id: str = ""
    name: str = ""
    spreadsheet_id: str = ""  # Created or provided spreadsheet ID
    root_folder_id: str = ""  # Created or provided folder ID
    sheets_created: list[str] = field(default_factory=list)
    folders_created: list[str] = field(default_factory=list)
    message: str = ""

    # Duplicate/similarity check results
    requires_confirmation: bool = False    # 確認が必要か
    duplicate_id: bool = False             # ID重複（エラー）
    duplicate_name: str = ""               # 名前重複したプロジェクトID（警告）
    similar_projects: list[SimilarProject] = field(default_factory=list)
    
    def has_warnings(self) -> bool:
        """Check if there are any warnings that need user attention."""
        return bool(self.duplicate_name or self.similar_projects)
    
    def format_warnings(self) -> str:
        """Format warnings for display."""
        lines = []
        
        if self.duplicate_name:
            lines.append(f"⚠️ 同名のプロジェクト '{self.duplicate_name}' が存在します。")
        
        if self.similar_projects:
            lines.append("📋 類似のプロジェクトが見つかりました:")
            for p in self.similar_projects:
                lines.append(f"  - {p.project_id} (類似度: {p.similarity_percent}%): {p.name}")
                if p.description:
                    lines.append(f"    {p.description[:50]}{'...' if len(p.description) > 50 else ''}")
        
        return "\n".join(lines)


@dataclass
class SwitchProjectResult:
    """Result of switching projects."""
    success: bool
    project_id: str = ""
    name: str = ""
    message: str = ""


@dataclass
class ListProjectsResult:
    """Result of listing projects."""
    success: bool
    projects: list[ProjectSummary] = field(default_factory=list)
    current_project: str = ""
    message: str = ""


@dataclass
class UpdateProjectResult:
    """Result of updating a project."""
    success: bool
    project_id: str = ""
    updated_fields: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class DeleteProjectResult:
    """Result of deleting a project."""
    success: bool
    project_id: str = ""
    message: str = ""
