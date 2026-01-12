"""Document operation tools for Spirrow-Prismind."""

import logging
from datetime import datetime
from typing import Optional

from ..integrations import (
    GoogleDocsClient,
    GoogleDriveClient,
    GoogleSheetsClient,
    RAGClient,
)
from ..models import (
    CatalogEntry,
    CreateDocumentResult,
    DocReference,
    Document,
    DocumentResult,
    UpdateDocumentResult,
)
from .project_tools import ProjectTools

logger = logging.getLogger(__name__)


class DocumentTools:
    """Tools for document operations."""

    # Document type to folder mapping
    DOC_TYPE_FOLDERS = {
        "設計書": "design_folder",
        "実装手順書": "procedure_folder",
    }

    def __init__(
        self,
        docs_client: GoogleDocsClient,
        drive_client: GoogleDriveClient,
        sheets_client: GoogleSheetsClient,
        rag_client: RAGClient,
        project_tools: ProjectTools,
        default_user: str = "default",
    ):
        """Initialize document tools.
        
        Args:
            docs_client: Google Docs client
            drive_client: Google Drive client
            sheets_client: Google Sheets client
            rag_client: RAG client
            project_tools: Project tools for config access
            default_user: Default user ID
        """
        self.docs = docs_client
        self.drive = drive_client
        self.sheets = sheets_client
        self.rag = rag_client
        self.project_tools = project_tools
        self.default_user = default_user

    def get_document(
        self,
        query: Optional[str] = None,
        doc_id: Optional[str] = None,
        doc_type: Optional[str] = None,
        phase_task: Optional[str] = None,
        user: Optional[str] = None,
    ) -> DocumentResult:
        """Get a document by search or direct ID.
        
        Args:
            query: Search query
            doc_id: Direct document ID
            doc_type: Document type filter
            phase_task: Phase-task filter (e.g., "P4-T01")
            user: User ID
            
        Returns:
            DocumentResult
        """
        user = user or self.default_user
        
        # If doc_id is specified, get directly
        if doc_id:
            return self._get_document_by_id(doc_id)
        
        # Otherwise, search catalog
        if not query:
            return DocumentResult(
                found=False,
                document=None,
                candidates=[],
                message="検索クエリまたはドキュメントIDを指定してください。",
            )
        
        # Get current project
        project_id = self.project_tools.get_current_project_id(user)
        
        # Search catalog in RAG
        result = self.rag.search_catalog(
            query=query,
            project=project_id,
            doc_type=doc_type,
            phase_task=phase_task,
            n_results=10,
        )
        
        if not result.success or not result.documents:
            return DocumentResult(
                found=False,
                document=None,
                candidates=[],
                message=f"'{query}' に一致するドキュメントが見つかりません。",
            )
        
        # If single result, fetch it
        if len(result.documents) == 1:
            meta = result.documents[0].metadata
            return self._get_document_by_id(meta.get("doc_id", ""))
        
        # Multiple results - return candidates
        candidates = []
        for doc in result.documents:
            meta = doc.metadata
            candidates.append(DocReference(
                name=meta.get("name", ""),
                doc_id=meta.get("doc_id", ""),
                reason=f"{meta.get('doc_type', '')} / {meta.get('phase_task', '')}",
            ))
        
        return DocumentResult(
            found=False,
            document=None,
            candidates=candidates,
            message=f"{len(candidates)} 件の候補が見つかりました。doc_id を指定して取得してください。",
        )

    def _get_document_by_id(self, doc_id: str) -> DocumentResult:
        """Get a document by its Google Docs ID.
        
        Args:
            doc_id: Google Docs document ID
            
        Returns:
            DocumentResult
        """
        try:
            # Get from Google Docs
            doc_content = self.docs.get_document(doc_id)
            
            # Get catalog entry from RAG for metadata
            catalog_result = self.rag.search_by_metadata(
                where={"doc_id": {"$eq": doc_id}},
                n_results=1,
            )
            
            metadata = {}
            doc_type = ""
            if catalog_result.success and catalog_result.documents:
                metadata = catalog_result.documents[0].metadata
                doc_type = metadata.get("doc_type", "")
            
            document = Document(
                doc_id=doc_id,
                name=doc_content.title,
                doc_type=doc_type,
                content=doc_content.body_text,
                source="Google Docs",
                metadata={
                    "url": doc_content.url,
                    "phase_task": metadata.get("phase_task", ""),
                    "feature": metadata.get("feature", ""),
                    "updated_at": metadata.get("updated_at", ""),
                },
            )
            
            return DocumentResult(
                found=True,
                document=document,
                candidates=[],
                message="",
            )
        except Exception as e:
            logger.error(f"Failed to get document '{doc_id}': {e}")
            return DocumentResult(
                found=False,
                document=None,
                candidates=[],
                message=f"ドキュメントの取得に失敗しました: {e}",
            )

    def create_document(
        self,
        name: str,
        doc_type: str,
        content: str,
        phase_task: str,
        feature: Optional[str] = None,
        keywords: Optional[list[str]] = None,
        reference_timing: Optional[str] = None,
        related_docs: Optional[list[str]] = None,
        user: Optional[str] = None,
    ) -> CreateDocumentResult:
        """Create a new document and register in catalog.
        
        Args:
            name: Document name
            doc_type: Document type (設計書/実装手順書/etc.)
            content: Document content
            phase_task: Phase-task identifier (e.g., "P4-T01")
            feature: Feature name
            keywords: Search keywords (auto-generated if None)
            reference_timing: When to reference (設計時/実装時/etc.)
            related_docs: Related document IDs
            user: User ID
            
        Returns:
            CreateDocumentResult
        """
        user = user or self.default_user
        
        # Get current project config
        config = self.project_tools.get_project_config(user=user)
        if not config:
            return CreateDocumentResult(
                success=False,
                doc_id="",
                name=name,
                doc_url="",
                source="",
                catalog_registered=False,
                message="プロジェクトが選択されていません。",
            )
        
        try:
            # Step 1: Create document in Google Docs
            doc_info = self.docs.create_document_with_content(
                title=name,
                content=content,
                heading=name,
            )
            
            doc_id = doc_info.doc_id
            doc_url = doc_info.url
            
            # Step 2: Move to appropriate folder
            folder_key = self.DOC_TYPE_FOLDERS.get(doc_type, "design_folder")
            folder_name = getattr(config.drive, folder_key, "")
            
            if folder_name:
                # Find or create the folder
                folder_info = self.drive.find_folder_by_name(
                    name=folder_name,
                    parent_id=config.root_folder_id,
                )
                
                if folder_info:
                    self.drive.move_file(doc_id, folder_info.file_id)
            
            # Step 3: Auto-generate keywords if not provided
            if keywords is None:
                keywords = self._generate_keywords(name, content, feature)
            
            # Step 4: Register in catalog (Sheets)
            catalog_registered = False
            try:
                self._register_in_sheets_catalog(
                    config=config,
                    doc_id=doc_id,
                    name=name,
                    doc_type=doc_type,
                    phase_task=phase_task,
                    feature=feature,
                    keywords=keywords,
                    reference_timing=reference_timing,
                )
                catalog_registered = True
            except Exception as e:
                logger.error(f"Failed to register in Sheets catalog: {e}")
            
            # Step 5: Register in RAG cache
            self.rag.add_catalog_entry(
                doc_id=doc_id,
                name=name,
                doc_type=doc_type,
                project=config.project_id,
                phase_task=phase_task,
                metadata={
                    "feature": feature or "",
                    "keywords": keywords,
                    "reference_timing": reference_timing or "",
                    "related_docs": related_docs or [],
                    "source": "Google Docs",
                    "url": doc_url,
                },
            )
            
            return CreateDocumentResult(
                success=True,
                doc_id=doc_id,
                name=name,
                doc_url=doc_url,
                source="Google Docs",
                catalog_registered=catalog_registered,
                message=f"ドキュメント '{name}' を作成しました。",
            )
            
        except Exception as e:
            logger.error(f"Failed to create document: {e}")
            return CreateDocumentResult(
                success=False,
                doc_id="",
                name=name,
                doc_url="",
                source="",
                catalog_registered=False,
                message=f"ドキュメントの作成に失敗しました: {e}",
            )

    def update_document(
        self,
        doc_id: str,
        content: Optional[str] = None,
        append: bool = False,
        metadata: Optional[dict] = None,
        user: Optional[str] = None,
    ) -> UpdateDocumentResult:
        """Update a document.
        
        Args:
            doc_id: Document ID
            content: New content (None to keep)
            append: If True, append content. If False, replace.
            metadata: Metadata updates
            user: User ID
            
        Returns:
            UpdateDocumentResult
        """
        user = user or self.default_user
        updated_fields = []
        
        try:
            # Update content if provided
            if content is not None:
                if append:
                    self.docs.append_text(doc_id, content)
                else:
                    self.docs.replace_all_text(doc_id, content)
                updated_fields.append("content")
            
            # Update catalog metadata in RAG
            if metadata:
                # Get existing catalog entry
                catalog_result = self.rag.search_by_metadata(
                    where={"doc_id": {"$eq": doc_id}},
                    n_results=1,
                )
                
                if catalog_result.success and catalog_result.documents:
                    existing = catalog_result.documents[0]
                    updated_meta = {**existing.metadata, **metadata}
                    updated_meta["updated_at"] = datetime.now().isoformat()
                    
                    # Re-add (update) the catalog entry
                    self.rag.update_document(
                        doc_id=existing.doc_id,
                        metadata=updated_meta,
                    )
                    
                    updated_fields.extend(metadata.keys())
            
            # Always update the updated_at timestamp
            if content is not None:
                catalog_result = self.rag.search_by_metadata(
                    where={"doc_id": {"$eq": doc_id}},
                    n_results=1,
                )
                
                if catalog_result.success and catalog_result.documents:
                    existing = catalog_result.documents[0]
                    existing.metadata["updated_at"] = datetime.now().isoformat()
                    self.rag.update_document(
                        doc_id=existing.doc_id,
                        metadata=existing.metadata,
                    )
            
            return UpdateDocumentResult(
                success=True,
                doc_id=doc_id,
                updated_fields=updated_fields,
                message=f"ドキュメントを更新しました: {', '.join(updated_fields)}",
            )
            
        except Exception as e:
            logger.error(f"Failed to update document '{doc_id}': {e}")
            return UpdateDocumentResult(
                success=False,
                doc_id=doc_id,
                updated_fields=[],
                message=f"ドキュメントの更新に失敗しました: {e}",
            )

    def _generate_keywords(
        self,
        name: str,
        content: str,
        feature: Optional[str],
    ) -> list[str]:
        """Generate keywords from document content.
        
        Args:
            name: Document name
            content: Document content
            feature: Feature name
            
        Returns:
            List of keywords
        """
        keywords = []
        
        # Add words from name
        for word in name.split():
            if len(word) >= 2:
                keywords.append(word)
        
        # Add feature
        if feature:
            keywords.append(feature)
        
        # Simple keyword extraction from content
        # In production, this could use more sophisticated NLP
        important_words = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("#") or line.startswith("##"):
                # Headings are likely important
                words = line.lstrip("#").strip().split()
                important_words.extend(w for w in words if len(w) >= 2)
        
        keywords.extend(important_words[:10])  # Limit
        
        # Deduplicate
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                unique_keywords.append(kw)
        
        return unique_keywords[:20]  # Limit total

    def _register_in_sheets_catalog(
        self,
        config,
        doc_id: str,
        name: str,
        doc_type: str,
        phase_task: str,
        feature: Optional[str],
        keywords: list[str],
        reference_timing: Optional[str],
    ):
        """Register document in Google Sheets catalog.
        
        Args:
            config: Project config
            doc_id: Document ID
            name: Document name
            doc_type: Document type
            phase_task: Phase-task
            feature: Feature name
            keywords: Keywords
            reference_timing: Reference timing
        """
        # Prepare row data
        row = [
            name,                           # ドキュメント名
            "Google Docs",                  # 保存先
            doc_id,                         # ID
            doc_type,                       # 種別
            config.project_id,              # プロジェクト
            phase_task,                     # フェーズタスク
            feature or "",                  # フィーチャー
            reference_timing or "",         # 参照タイミング
            "",                             # 関連ドキュメント
            ", ".join(keywords),            # キーワード
            datetime.now().strftime("%Y-%m-%d"),  # 更新日
            "",                             # 作成者
            "active",                       # ステータス
        ]
        
        # Append to catalog sheet
        self.sheets.append_rows(
            spreadsheet_id=config.spreadsheet_id,
            range_name=f"{config.sheets.catalog}!A:M",
            values=[row],
        )
