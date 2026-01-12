"""Catalog management tools for Spirrow-Prismind."""

import logging
from datetime import datetime
from typing import Optional

from ..integrations import GoogleSheetsClient, RAGClient
from ..models import CatalogEntry, SearchCatalogResult, SyncCatalogResult
from .project_tools import ProjectTools

logger = logging.getLogger(__name__)


class CatalogTools:
    """Tools for catalog management."""

    def __init__(
        self,
        rag_client: RAGClient,
        sheets_client: GoogleSheetsClient,
        project_tools: ProjectTools,
        default_user: str = "default",
    ):
        """Initialize catalog tools.
        
        Args:
            rag_client: RAG client for catalog cache
            sheets_client: Google Sheets client for master catalog
            project_tools: Project tools for config access
            default_user: Default user ID
        """
        self.rag = rag_client
        self.sheets = sheets_client
        self.project_tools = project_tools
        self.default_user = default_user

    def search_catalog(
        self,
        query: Optional[str] = None,
        project: Optional[str] = None,
        doc_type: Optional[str] = None,
        phase_task: Optional[str] = None,
        feature: Optional[str] = None,
        reference_timing: Optional[str] = None,
        status: str = "active",
        limit: int = 10,
        user: Optional[str] = None,
    ) -> SearchCatalogResult:
        """Search the catalog.
        
        Args:
            query: Free text search query
            project: Filter by project (None for current)
            doc_type: Filter by document type
            phase_task: Filter by phase-task
            feature: Filter by feature
            reference_timing: Filter by reference timing
            status: Filter by status (active/archived/all)
            limit: Maximum results
            user: User ID
            
        Returns:
            SearchCatalogResult
        """
        user = user or self.default_user
        
        # Get project if not specified
        if project is None:
            project = self.project_tools.get_current_project_id(user)
        
        # Build search
        if query:
            # Semantic search with filters
            result = self.rag.search_catalog(
                query=query,
                project=project,
                doc_type=doc_type,
                phase_task=phase_task,
                n_results=limit * 2,  # Get more for filtering
            )
        else:
            # Metadata-only search
            where = {"type": {"$eq": "catalog"}}
            
            if project:
                where["project"] = {"$eq": project}
            if doc_type:
                where["doc_type"] = {"$eq": doc_type}
            if phase_task:
                where["phase_task"] = {"$eq": phase_task}
            
            result = self.rag.search_by_metadata(
                where=where,
                n_results=limit * 2,
            )
        
        if not result.success:
            return SearchCatalogResult(
                success=False,
                total_count=0,
                documents=[],
                message=f"検索に失敗しました: {result.message}",
            )
        
        # Convert to CatalogEntry and filter
        documents = []
        for doc in result.documents:
            meta = doc.metadata
            
            # Apply additional filters
            if feature and meta.get("feature") != feature:
                continue
            
            if reference_timing and meta.get("reference_timing") != reference_timing:
                continue
            
            if status != "all":
                doc_status = meta.get("status", "active")
                if doc_status != status:
                    continue
            
            # Parse updated_at
            updated_at_str = meta.get("updated_at", "")
            try:
                updated_at = datetime.fromisoformat(updated_at_str) if updated_at_str else datetime.now()
            except ValueError:
                updated_at = datetime.now()
            
            documents.append(CatalogEntry(
                doc_id=meta.get("doc_id", ""),
                name=meta.get("name", ""),
                doc_type=meta.get("doc_type", ""),
                project=meta.get("project", ""),
                phase_task=meta.get("phase_task", ""),
                feature=meta.get("feature", ""),
                source=meta.get("source", "Google Docs"),
                updated_at=updated_at,
                keywords=meta.get("keywords", []),
                reference_timing=meta.get("reference_timing", ""),
            ))
            
            if len(documents) >= limit:
                break
        
        return SearchCatalogResult(
            success=True,
            total_count=len(documents),
            documents=documents,
            message=f"{len(documents)} 件のドキュメントが見つかりました。",
        )

    def sync_catalog(
        self,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> SyncCatalogResult:
        """Sync catalog from Google Sheets to RAG cache.
        
        Args:
            project: Project to sync (None for current)
            user: User ID
            
        Returns:
            SyncCatalogResult
        """
        user = user or self.default_user
        
        # Get project config
        if project is None:
            project = self.project_tools.get_current_project_id(user)
        
        if not project:
            return SyncCatalogResult(
                success=False,
                synced_count=0,
                message="プロジェクトが選択されていません。",
            )
        
        config = self.project_tools.get_project_config(project, user)
        if not config:
            return SyncCatalogResult(
                success=False,
                synced_count=0,
                message=f"プロジェクト '{project}' の設定が見つかりません。",
            )
        
        try:
            # Read from Google Sheets
            range_name = f"{config.sheets.catalog}!A:M"
            result = self.sheets.read_range(
                spreadsheet_id=config.spreadsheet_id,
                range_name=range_name,
            )
            
            rows = result.get("values", [])
            
            if not rows:
                return SyncCatalogResult(
                    success=True,
                    synced_count=0,
                    message="目録にデータがありません。",
                )
            
            # Skip header row if present
            start_row = 0
            if rows and rows[0] and rows[0][0] in ["ドキュメント名", "名前", "Name"]:
                start_row = 1
            
            # Clear existing catalog entries in RAG
            deleted_count = self.rag.delete_catalog_entries_by_project(project)
            logger.info(f"Deleted {deleted_count} existing catalog entries for project {project}")
            
            # Add new entries
            synced_count = 0
            for row in rows[start_row:]:
                if len(row) < 4:  # Minimum required columns
                    continue
                
                # Parse row
                # Expected columns: ドキュメント名, 保存先, ID, 種別, プロジェクト, フェーズタスク, フィーチャー, 参照タイミング, 関連ドキュメント, キーワード, 更新日, 作成者, ステータス
                name = row[0] if len(row) > 0 else ""
                source = row[1] if len(row) > 1 else ""
                doc_id = row[2] if len(row) > 2 else ""
                doc_type = row[3] if len(row) > 3 else ""
                # row[4] is project, skip as we're using the parameter
                phase_task = row[5] if len(row) > 5 else ""
                feature = row[6] if len(row) > 6 else ""
                reference_timing = row[7] if len(row) > 7 else ""
                related_docs = row[8] if len(row) > 8 else ""
                keywords_str = row[9] if len(row) > 9 else ""
                updated_at = row[10] if len(row) > 10 else ""
                creator = row[11] if len(row) > 11 else ""
                status = row[12] if len(row) > 12 else "active"
                
                if not name or not doc_id:
                    continue
                
                # Parse keywords
                keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
                
                # Parse related docs
                related_doc_list = [d.strip() for d in related_docs.split(",") if d.strip()]
                
                # Add to RAG
                self.rag.add_catalog_entry(
                    doc_id=doc_id,
                    name=name,
                    doc_type=doc_type,
                    project=project,
                    phase_task=phase_task,
                    metadata={
                        "feature": feature,
                        "keywords": keywords,
                        "reference_timing": reference_timing,
                        "related_docs": related_doc_list,
                        "source": source,
                        "updated_at": updated_at,
                        "creator": creator,
                        "status": status,
                    },
                )
                
                synced_count += 1
            
            return SyncCatalogResult(
                success=True,
                synced_count=synced_count,
                message=f"{synced_count} 件の目録エントリを同期しました。",
            )
            
        except Exception as e:
            logger.error(f"Failed to sync catalog: {e}")
            return SyncCatalogResult(
                success=False,
                synced_count=0,
                message=f"目録の同期に失敗しました: {e}",
            )

    def get_document_by_phase_task(
        self,
        phase_task: str,
        doc_type: Optional[str] = None,
        user: Optional[str] = None,
    ) -> list[CatalogEntry]:
        """Get documents by phase-task.
        
        Args:
            phase_task: Phase-task identifier (e.g., "P4-T01")
            doc_type: Optional document type filter
            user: User ID
            
        Returns:
            List of matching CatalogEntry
        """
        result = self.search_catalog(
            phase_task=phase_task,
            doc_type=doc_type,
            limit=100,
            user=user,
        )
        
        return result.documents if result.success else []

    def get_documents_by_feature(
        self,
        feature: str,
        user: Optional[str] = None,
    ) -> list[CatalogEntry]:
        """Get documents by feature.
        
        Args:
            feature: Feature name
            user: User ID
            
        Returns:
            List of matching CatalogEntry
        """
        result = self.search_catalog(
            feature=feature,
            limit=100,
            user=user,
        )
        
        return result.documents if result.success else []
