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
    DeleteDocumentResult,
    DeleteDocumentTypeResult,
    DocReference,
    Document,
    DocumentResult,
    DocumentSummary,
    DocumentType,
    ListDocumentTypesResult,
    ListDocumentsResult,
    RegisterDocumentTypeResult,
    UpdateDocumentResult,
)
from .global_document_types import GlobalDocumentTypeStorage
from .project_tools import ProjectTools

logger = logging.getLogger(__name__)


class DocumentTools:
    """Tools for document operations."""

    def __init__(
        self,
        docs_client: GoogleDocsClient,
        drive_client: GoogleDriveClient,
        sheets_client: GoogleSheetsClient,
        rag_client: RAGClient,
        project_tools: ProjectTools,
        user_name: str = "default",
    ):
        """Initialize document tools.
        
        Args:
            docs_client: Google Docs client
            drive_client: Google Drive client
            sheets_client: Google Sheets client
            rag_client: RAG client
            project_tools: Project tools for config access
            user_name: Default user ID
        """
        self.docs = docs_client
        self.drive = drive_client
        self.sheets = sheets_client
        self.rag = rag_client
        self.project_tools = project_tools
        self.user_name = user_name

    def get_document(
        self,
        query: Optional[str] = None,
        doc_id: Optional[str] = None,
        doc_type: Optional[str] = None,
        phase_task: Optional[str] = None,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> DocumentResult:
        """Get a document by search or direct ID.

        Args:
            query: Search query
            doc_id: Direct document ID
            doc_type: Document type filter
            phase_task: Phase-task filter (e.g., "P4-T01")
            project: Project ID (uses current project if omitted)
            user: User ID

        Returns:
            DocumentResult
        """
        user = user or self.user_name

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

        # Determine project: explicit > current project
        project_id = project or self.project_tools.get_current_project_id(user)
        
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
        project: Optional[str] = None,
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
            project: Project ID (uses current project if omitted)
            user: User ID

        Returns:
            CreateDocumentResult
        """
        user = user or self.user_name

        # Determine project config: explicit project > current project
        if project:
            config = self.project_tools.get_project_config(project=project, user=user)
        else:
            config = self.project_tools.get_project_config(user=user)
        if not config:
            return CreateDocumentResult(
                success=False,
                doc_id="",
                name=name,
                doc_type=doc_type,
                doc_url="",
                source="",
                catalog_registered=False,
                unknown_doc_type=False,
                message="プロジェクトが選択されていません。",
            )

        # Step 1: Resolve document type - reject unknown types
        doc_type_obj = self.get_document_type(doc_type, user=user)

        if not doc_type_obj:
            # Unknown doc_type - do NOT create, return flag
            return CreateDocumentResult(
                success=False,
                doc_id="",
                name=name,
                doc_type=doc_type,
                doc_url="",
                source="",
                catalog_registered=False,
                unknown_doc_type=True,
                message=f"ドキュメントタイプ '{doc_type}' は登録されていません。"
                "register_document_type で登録してください。",
            )

        try:
            # Step 2: Get folder ID from cached folder_ids (avoids name search)
            target_folder_id = doc_type_obj.get_folder_id(config.project_id)

            if not target_folder_id:
                # Folder ID not cached - create/find folder and cache the ID
                # This happens on first use or during migration from old data
                folder_path = doc_type_obj.folder_name  # e.g., "設計/詳細設計"

                if folder_path and config.root_folder_id:
                    # Use ensure_folder_path for nested paths
                    folder_info, created = self.drive.ensure_folder_path(
                        path=folder_path,
                        parent_id=config.root_folder_id,
                    )
                    if folder_info:
                        target_folder_id = folder_info.file_id
                        if created:
                            logger.info(f"Created folder path '{folder_path}' in project folder")

                        # Cache the folder ID for future use (auto-migration)
                        doc_type_obj.set_folder_id(config.project_id, target_folder_id)
                        self._save_document_type(doc_type_obj)
                        logger.info(
                            f"Cached folder ID for doc_type '{doc_type_obj.type_id}' "
                            f"in project '{config.project_id}'"
                        )
                else:
                    # No folder path - use project root
                    target_folder_id = config.root_folder_id

            # Step 3: Create document in the correct folder using Drive API
            file_info = self.drive.create_document(
                name=name,
                parent_id=target_folder_id,
            )
            doc_id = file_info.file_id
            doc_url = file_info.web_view_link or f"https://docs.google.com/document/d/{doc_id}/edit"

            # Step 4: Add content using Docs API
            if content:
                # Add heading first
                heading_text = name + "\n"
                self.docs.insert_text(doc_id, heading_text, index=1)
                # Apply heading style
                self.docs.service.documents().batchUpdate(
                    documentId=doc_id,
                    body={"requests": [{
                        "updateParagraphStyle": {
                            "range": {"startIndex": 1, "endIndex": 1 + len(heading_text)},
                            "paragraphStyle": {"namedStyleType": "HEADING_1"},
                            "fields": "namedStyleType",
                        }
                    }]},
                ).execute()
                # Add content after heading
                self.docs.insert_text(doc_id, content, index=1 + len(heading_text))

            # Step 5: Auto-generate keywords if not provided
            if keywords is None:
                keywords = self._generate_keywords(name, content, feature)

            # Step 6: Register in catalog (Sheets)
            catalog_registered = False
            catalog_warning = ""
            try:
                # Check if catalog sheet exists
                if not self.sheets.sheet_exists(config.spreadsheet_id, config.sheets.catalog):
                    catalog_warning = f"目録シート '{config.sheets.catalog}' が見つかりません。RAGのみに登録しました。"
                    logger.warning(catalog_warning)
                else:
                    self._register_in_sheets_catalog(
                        config=config,
                        doc_id=doc_id,
                        name=name,
                        doc_type=doc_type_obj.name,
                        phase_task=phase_task,
                        feature=feature,
                        keywords=keywords,
                        reference_timing=reference_timing,
                    )
                    catalog_registered = True
            except Exception as e:
                logger.error(f"Failed to register in Sheets catalog: {e}")
                catalog_warning = f"目録シートへの登録に失敗しました: {e}"

            # Step 7: Register in RAG cache
            self.rag.add_catalog_entry(
                doc_id=doc_id,
                name=name,
                doc_type=doc_type_obj.name,
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

            message = f"ドキュメント '{name}' を作成しました。"
            if catalog_warning:
                message += f" ({catalog_warning})"

            return CreateDocumentResult(
                success=True,
                doc_id=doc_id,
                name=name,
                doc_type=doc_type_obj.name,
                doc_url=doc_url,
                source="Google Docs",
                catalog_registered=catalog_registered,
                unknown_doc_type=False,
                message=message,
            )

        except Exception as e:
            logger.error(f"Failed to create document: {e}")
            return CreateDocumentResult(
                success=False,
                doc_id="",
                name=name,
                doc_type=doc_type,
                doc_url="",
                source="",
                catalog_registered=False,
                unknown_doc_type=False,
                message=f"ドキュメントの作成に失敗しました: {e}",
            )

    def update_document(
        self,
        doc_id: str,
        content: Optional[str] = None,
        append: bool = False,
        metadata: Optional[dict] = None,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> UpdateDocumentResult:
        """Update a document.

        Args:
            doc_id: Document ID
            content: New content (None to keep)
            append: If True, append content. If False, replace.
            metadata: Metadata updates (can include doc_type, phase_task, feature)
            project: Project ID (uses current project if omitted)
            user: User ID

        Returns:
            UpdateDocumentResult
        """
        user = user or self.user_name
        updated_fields = []

        try:
            # Update content if provided
            if content is not None:
                if append:
                    self.docs.append_text(doc_id, content)
                else:
                    self.docs.replace_all_text(doc_id, content)
                updated_fields.append("content")

            # Handle doc_type change - move file to new folder
            if metadata and "doc_type" in metadata:
                new_doc_type = metadata["doc_type"]
                doc_type_obj = self.get_document_type(new_doc_type, user=user)

                if not doc_type_obj:
                    return UpdateDocumentResult(
                        success=False,
                        doc_id=doc_id,
                        updated_fields=updated_fields,
                        message=f"ドキュメントタイプ '{new_doc_type}' は登録されていません。",
                    )

                # Determine project config: explicit project > current project
                if project:
                    config = self.project_tools.get_project_config(project=project, user=user)
                else:
                    config = self.project_tools.get_project_config(user=user)
                if config and config.root_folder_id and doc_type_obj.folder_name:
                    try:
                        # Try to get cached folder ID first
                        target_folder_id = doc_type_obj.get_folder_id(config.project_id)

                        if not target_folder_id:
                            # Folder ID not cached - create/find folder and cache
                            folder_info, _ = self.drive.ensure_folder_path(
                                path=doc_type_obj.folder_name,
                                parent_id=config.root_folder_id,
                            )
                            if folder_info:
                                target_folder_id = folder_info.file_id
                                # Cache the folder ID
                                doc_type_obj.set_folder_id(config.project_id, target_folder_id)
                                self._save_document_type(doc_type_obj)

                        if target_folder_id:
                            # Move the document to the target folder
                            self.drive.move_file(doc_id, target_folder_id)
                            logger.info(
                                f"Moved document '{doc_id}' to folder "
                                f"'{doc_type_obj.folder_name}'"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to move document to new folder: {e}")

                # Update doc_type in metadata (will be stored in the display name)
                metadata["doc_type"] = doc_type_obj.name

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

                    # Update Sheets catalog if doc_type, phase_task, or feature changed
                    # Determine project config: explicit project > current project
                    if project:
                        config = self.project_tools.get_project_config(project=project, user=user)
                    else:
                        config = self.project_tools.get_project_config(user=user)
                    if config and config.spreadsheet_id:
                        self._update_sheets_catalog_row(
                            config=config,
                            doc_id=doc_id,
                            updates=metadata,
                        )

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

    def _update_sheets_catalog_row(
        self,
        config,
        doc_id: str,
        updates: dict,
    ):
        """Update specific fields in the Sheets catalog row.

        Args:
            config: Project config
            doc_id: Document ID
            updates: Fields to update (doc_type, phase_task, feature)
        """
        try:
            # Find the row by doc_id (column C, index 2)
            row_number = self.sheets.find_row_by_value(
                spreadsheet_id=config.spreadsheet_id,
                sheet_name=config.sheets.catalog,
                column_index=2,  # ID column
                value=doc_id,
            )

            if not row_number:
                logger.warning(f"Document '{doc_id}' not found in Sheets catalog")
                return

            # Get current row data
            range_name = f"{config.sheets.catalog}!A{row_number}:M{row_number}"
            current_values = self.sheets.get_sheet_values(
                config.spreadsheet_id, range_name
            )

            if not current_values or not current_values[0]:
                return

            row = list(current_values[0])
            # Extend row if needed
            while len(row) < 13:
                row.append("")

            # Column mapping:
            # 0: name, 1: source, 2: doc_id, 3: doc_type, 4: project,
            # 5: phase_task, 6: feature, 7: reference_timing, 8: related_docs,
            # 9: keywords, 10: updated_at, 11: author, 12: status

            if "doc_type" in updates:
                row[3] = updates["doc_type"]
            if "phase_task" in updates:
                row[5] = updates["phase_task"]
            if "feature" in updates:
                row[6] = updates["feature"]

            # Update the updated_at field
            row[10] = datetime.now().strftime("%Y-%m-%d")

            # Write back
            self.sheets.update_row(
                spreadsheet_id=config.spreadsheet_id,
                sheet_name=config.sheets.catalog,
                row_number=row_number,
                values=row,
            )

        except Exception as e:
            logger.warning(f"Failed to update Sheets catalog row: {e}")

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

    def list_document_types(
        self,
        user: Optional[str] = None,
    ) -> ListDocumentTypesResult:
        """List available document types for the current project.

        Merges global types and project-specific types. When both have the
        same type_id, project-specific type takes precedence (override).

        Args:
            user: User ID

        Returns:
            ListDocumentTypesResult
        """
        user = user or self.user_name

        # Step 1: Get global types (with RAG client for semantic search)
        global_storage = GlobalDocumentTypeStorage(rag_client=self.rag)
        global_types = global_storage.get_all()

        # Build merged dict (global first, then project overrides)
        all_types_dict: dict[str, DocumentType] = {}
        for doc_type in global_types:
            all_types_dict[doc_type.type_id] = doc_type

        # Step 2: Get project-specific types (these can override global)
        config = self.project_tools.get_project_config(user=user)
        if config and config.document_types:
            for type_data in config.document_types:
                doc_type = DocumentType.from_dict(type_data)
                all_types_dict[doc_type.type_id] = doc_type

        all_types = list(all_types_dict.values())

        return ListDocumentTypesResult(
            success=True,
            document_types=all_types,
            message=f"{len(all_types)} 件のドキュメントタイプが利用可能です。",
        )

    def register_document_type(
        self,
        type_id: str,
        name: str,
        folder_name: str,
        scope: str = "global",
        template_doc_id: Optional[str] = None,
        description: Optional[str] = None,
        fields: Optional[list[str]] = None,
        create_folder: bool = True,
        user: Optional[str] = None,
    ) -> RegisterDocumentTypeResult:
        """Register a new custom document type.

        Args:
            type_id: Unique ID for the document type (e.g., "meeting_notes")
            name: Display name (e.g., "議事録")
            folder_name: Folder name in Google Drive
            scope: "global" for shared types, "project" for project-specific
            template_doc_id: Optional Google Docs template ID
            description: Description of the document type
            fields: Custom metadata fields
            create_folder: If True, create the folder in Google Drive
            user: User ID

        Returns:
            RegisterDocumentTypeResult
        """
        user = user or self.user_name

        # Validate type_id (ASCII alphanumeric and underscore only)
        if not type_id or not all(c.isascii() and (c.isalnum() or c == "_") for c in type_id):
            return RegisterDocumentTypeResult(
                success=False,
                type_id=type_id,
                message="type_id はASCII英数字とアンダースコアのみ使用できます（日本語不可）。",
            )

        # Validate scope
        if scope not in ("global", "project"):
            return RegisterDocumentTypeResult(
                success=False,
                type_id=type_id,
                message=f"scope は 'global' または 'project' である必要があります: {scope}",
            )

        # Create the document type
        new_type = DocumentType(
            type_id=type_id,
            name=name,
            folder_name=folder_name,
            template_doc_id=template_doc_id or "",
            description=description or "",
            fields=fields or [],
            is_global=(scope == "global"),
        )

        if scope == "global":
            # Register to global storage (with RAG client for semantic search)
            global_storage = GlobalDocumentTypeStorage(rag_client=self.rag)

            # Check for existing global type with same ID
            if global_storage.exists(type_id):
                return RegisterDocumentTypeResult(
                    success=False,
                    type_id=type_id,
                    message=f"グローバルタイプ '{type_id}' は既に登録されています。",
                )

            # Register global type
            if not global_storage.register(new_type):
                return RegisterDocumentTypeResult(
                    success=False,
                    type_id=type_id,
                    message=f"グローバルタイプの登録に失敗しました。",
                )

            logger.info(f"Registered global document type '{type_id}' ({name})")

            # Note: Global types don't create folders (no project context)
            # Folders are created on-demand when creating documents

            return RegisterDocumentTypeResult(
                success=True,
                type_id=type_id,
                name=name,
                folder_created=False,
                message=f"グローバルドキュメントタイプ '{name}' を登録しました。",
            )

        else:
            # Project-specific type
            # Get current project config
            config = self.project_tools.get_project_config(user=user)
            if not config:
                return RegisterDocumentTypeResult(
                    success=False,
                    type_id=type_id,
                    message="プロジェクトが選択されていません。",
                )

            # Check for existing project type with same ID
            for existing in config.document_types:
                if existing.get("type_id") == type_id:
                    return RegisterDocumentTypeResult(
                        success=False,
                        type_id=type_id,
                        message=f"プロジェクトタイプ '{type_id}' は既に登録されています。",
                    )

            # Create folder in Google Drive if requested
            folder_created = False
            if create_folder and config.root_folder_id:
                try:
                    existing_folder = self.drive.find_folder_by_name(
                        name=folder_name,
                        parent_id=config.root_folder_id,
                    )
                    if not existing_folder:
                        self.drive.create_folder(
                            name=folder_name,
                            parent_id=config.root_folder_id,
                        )
                        folder_created = True
                        logger.info(f"Created folder '{folder_name}' for document type '{type_id}'")
                except Exception as e:
                    logger.warning(f"Failed to create folder '{folder_name}': {e}")

            # Add to project config
            config.document_types.append(new_type.to_dict())

            # Save updated config
            try:
                config_data = {
                    "spreadsheet_id": config.spreadsheet_id,
                    "root_folder_id": config.root_folder_id,
                    "sheets": config.sheets.to_dict() if config.sheets else {},
                    "drive": config.drive.to_dict() if config.drive else {},
                    "docs": config.docs.to_dict() if config.docs else {},
                    "options": config.options.to_dict() if config.options else {},
                    "document_types": config.document_types,
                    "created_at": config.created_at.isoformat() if config.created_at else "",
                }
                self.project_tools._save_project_config_with_fallback(
                    project_id=config.project_id,
                    name=config.name,
                    description=config.description,
                    config_data=config_data,
                )
                logger.info(f"Registered project document type '{type_id}' ({name})")

                return RegisterDocumentTypeResult(
                    success=True,
                    type_id=type_id,
                    name=name,
                    folder_created=folder_created,
                    message=f"プロジェクトドキュメントタイプ '{name}' を登録しました。"
                    + (f" フォルダ '{folder_name}' を作成しました。" if folder_created else ""),
                )
            except Exception as e:
                logger.error(f"Failed to save document type: {e}")
                return RegisterDocumentTypeResult(
                    success=False,
                    type_id=type_id,
                    message=f"ドキュメントタイプの保存に失敗しました: {e}",
                )

    def delete_document_type(
        self,
        type_id: str,
        scope: str = "global",
        user: Optional[str] = None,
    ) -> DeleteDocumentTypeResult:
        """Delete a custom document type.

        Args:
            type_id: ID of the document type to delete
            scope: "global" for shared types, "project" for project-specific
            user: User ID

        Returns:
            DeleteDocumentTypeResult
        """
        user = user or self.user_name

        # Validate scope
        if scope not in ("global", "project"):
            return DeleteDocumentTypeResult(
                success=False,
                type_id=type_id,
                message=f"scope は 'global' または 'project' である必要があります: {scope}",
            )

        if scope == "global":
            # Delete from global storage (with RAG client for sync)
            global_storage = GlobalDocumentTypeStorage(rag_client=self.rag)

            if not global_storage.exists(type_id):
                return DeleteDocumentTypeResult(
                    success=False,
                    type_id=type_id,
                    message=f"グローバルタイプ '{type_id}' が見つかりません。",
                )

            if not global_storage.delete(type_id):
                return DeleteDocumentTypeResult(
                    success=False,
                    type_id=type_id,
                    message=f"グローバルタイプの削除に失敗しました。",
                )

            logger.info(f"Deleted global document type '{type_id}'")

            return DeleteDocumentTypeResult(
                success=True,
                type_id=type_id,
                message=f"グローバルドキュメントタイプ '{type_id}' を削除しました。",
            )

        else:
            # Project-specific type
            # Get current project config
            config = self.project_tools.get_project_config(user=user)
            if not config:
                return DeleteDocumentTypeResult(
                    success=False,
                    type_id=type_id,
                    message="プロジェクトが選択されていません。",
                )

            # Find and remove the document type
            original_count = len(config.document_types)
            config.document_types = [
                dt for dt in config.document_types if dt.get("type_id") != type_id
            ]

            if len(config.document_types) == original_count:
                return DeleteDocumentTypeResult(
                    success=False,
                    type_id=type_id,
                    message=f"プロジェクトタイプ '{type_id}' が見つかりません。",
                )

            # Save updated config
            try:
                config_data = {
                    "spreadsheet_id": config.spreadsheet_id,
                    "root_folder_id": config.root_folder_id,
                    "sheets": config.sheets.to_dict() if config.sheets else {},
                    "drive": config.drive.to_dict() if config.drive else {},
                    "docs": config.docs.to_dict() if config.docs else {},
                    "options": config.options.to_dict() if config.options else {},
                    "document_types": config.document_types,
                    "created_at": config.created_at.isoformat() if config.created_at else "",
                }
                self.project_tools._save_project_config_with_fallback(
                    project_id=config.project_id,
                    name=config.name,
                    description=config.description,
                    config_data=config_data,
                )
                logger.info(f"Deleted project document type '{type_id}'")

                return DeleteDocumentTypeResult(
                    success=True,
                    type_id=type_id,
                    message=f"プロジェクトドキュメントタイプ '{type_id}' を削除しました。",
                )
            except Exception as e:
                logger.error(f"Failed to delete document type: {e}")
                return DeleteDocumentTypeResult(
                    success=False,
                    type_id=type_id,
                    message=f"ドキュメントタイプの削除に失敗しました: {e}",
                )

    def get_document_type(
        self,
        type_id_or_name: str,
        user: Optional[str] = None,
    ) -> Optional[DocumentType]:
        """Get a document type by ID or name.

        Args:
            type_id_or_name: Document type ID or name
            user: User ID

        Returns:
            DocumentType if found, None otherwise
        """
        result = self.list_document_types(user=user)
        if not result.success:
            return None

        for doc_type in result.document_types:
            if doc_type.type_id == type_id_or_name or doc_type.name == type_id_or_name:
                return doc_type

        return None

    def _save_document_type(self, doc_type: DocumentType) -> bool:
        """Save a document type (update folder_ids, etc.).

        Saves to global storage if is_global, otherwise to project config.

        Args:
            doc_type: Document type to save

        Returns:
            True if saved successfully, False otherwise
        """
        if doc_type.is_global:
            # Update global storage
            global_storage = GlobalDocumentTypeStorage(rag_client=self.rag)
            return global_storage.update(doc_type)
        else:
            # Update project config
            config = self.project_tools.get_project_config()
            if not config:
                return False

            # Find and update the document type in project config
            for i, type_data in enumerate(config.document_types):
                if type_data.get("type_id") == doc_type.type_id:
                    config.document_types[i] = doc_type.to_dict()
                    break
            else:
                # Not found - add it
                config.document_types.append(doc_type.to_dict())

            # Save updated config
            try:
                config_data = {
                    "spreadsheet_id": config.spreadsheet_id,
                    "root_folder_id": config.root_folder_id,
                    "sheets": config.sheets.to_dict() if config.sheets else {},
                    "drive": config.drive.to_dict() if config.drive else {},
                    "docs": config.docs.to_dict() if config.docs else {},
                    "options": config.options.to_dict() if config.options else {},
                    "document_types": config.document_types,
                    "created_at": config.created_at.isoformat() if config.created_at else "",
                }
                self.project_tools._save_project_config_with_fallback(
                    project_id=config.project_id,
                    name=config.name,
                    description=config.description,
                    config_data=config_data,
                )
                return True
            except Exception as e:
                logger.error(f"Failed to save document type to project config: {e}")
                return False

    def find_similar_document_type(
        self,
        type_query: str,
        threshold: float = 0.75,
        user: Optional[str] = None,
    ) -> dict:
        """Find a document type semantically similar to the query.

        Uses RAG-based semantic search (BGE-M3 embeddings) for multilingual matching.
        Falls back to local string matching when RAG is unavailable.

        Args:
            type_query: Search query (type name, ID, or description)
            threshold: Minimum similarity score (0.0-1.0)
            user: User ID

        Returns:
            Dict containing:
            - found: Whether a match was found
            - type_id: Matched type ID (if found)
            - name: Matched type name (if found)
            - folder_name: Matched type folder name (if found)
            - similarity: Similarity score (if found)
            - message: Status message
        """
        user = user or self.user_name

        # Get global storage with RAG client
        global_storage = GlobalDocumentTypeStorage(rag_client=self.rag)

        # Try to find similar type
        doc_type, score = global_storage.find_similar_with_score(
            query=type_query,
            threshold=threshold,
        )

        if doc_type:
            return {
                "found": True,
                "type_id": doc_type.type_id,
                "name": doc_type.name,
                "folder_name": doc_type.folder_name,
                "description": doc_type.description,
                "similarity": score,
                "message": f"Found similar document type '{doc_type.type_id}' (similarity: {score:.3f})",
            }

        # Also check project-specific types
        config = self.project_tools.get_project_config(user=user)
        if config and config.document_types:
            # Simple local matching for project types
            query_lower = type_query.lower().replace("-", "_").replace(" ", "_")
            for type_data in config.document_types:
                type_id = type_data.get("type_id", "")
                name = type_data.get("name", "")
                if (
                    type_id.lower() == query_lower
                    or name.lower() == query_lower
                    or type_id.lower() in query_lower
                    or query_lower in type_id.lower()
                ):
                    return {
                        "found": True,
                        "type_id": type_id,
                        "name": name,
                        "folder_name": type_data.get("folder_name", ""),
                        "description": type_data.get("description", ""),
                        "similarity": 0.8,  # Synthetic score for local match
                        "message": f"Found project document type '{type_id}'",
                    }

        return {
            "found": False,
            "type_id": "",
            "name": "",
            "folder_name": "",
            "description": "",
            "similarity": 0.0,
            "message": f"No document type similar to '{type_query}' found (threshold: {threshold})",
        }

    def delete_document(
        self,
        doc_id: str,
        project: str,
        delete_drive_file: bool = False,
        soft_delete: bool = True,
        user: Optional[str] = None,
    ) -> DeleteDocumentResult:
        """Delete a document and its catalog entries.

        Args:
            doc_id: Document ID to delete
            project: Project name (required for safety)
            delete_drive_file: If True, delete the Drive file
            soft_delete: If True, move to trash. If False, permanently delete.
            user: User ID

        Returns:
            DeleteDocumentResult
        """
        user = user or self.user_name

        # Step 1: Verify the document belongs to the specified project
        catalog_entry = self.rag.get_catalog_entry(doc_id, project)
        if not catalog_entry:
            return DeleteDocumentResult(
                success=False,
                doc_id=doc_id,
                project=project,
                message=f"ドキュメント '{doc_id}' がプロジェクト '{project}' に見つかりません。",
            )

        # Verify project matches
        entry_project = catalog_entry.metadata.get("project", "")
        if entry_project != project:
            return DeleteDocumentResult(
                success=False,
                doc_id=doc_id,
                project=project,
                message=f"ドキュメントはプロジェクト '{entry_project}' に属しています。"
                f"指定されたプロジェクト '{project}' と一致しません。",
            )

        catalog_deleted = False
        sheet_row_deleted = False
        drive_file_deleted = False
        knowledge_deleted_count = 0

        try:
            # Step 2: Delete RAG catalog entry
            rag_result = self.rag.delete_catalog_entry(doc_id, project)
            catalog_deleted = rag_result.success

            # Step 3: Delete from Google Sheets catalog
            config = self.project_tools.get_project_config(user=user)
            if config and config.spreadsheet_id:
                try:
                    # Find the row by doc_id (column C, index 2)
                    row_number = self.sheets.find_row_by_value(
                        spreadsheet_id=config.spreadsheet_id,
                        sheet_name=config.sheets.catalog,
                        column_index=2,  # ID column
                        value=doc_id,
                    )
                    if row_number:
                        self.sheets.delete_row(
                            spreadsheet_id=config.spreadsheet_id,
                            sheet_name=config.sheets.catalog,
                            row_number=row_number,
                        )
                        sheet_row_deleted = True
                except Exception as e:
                    logger.warning(f"Failed to delete Sheets row for '{doc_id}': {e}")

            # Step 4: Delete Drive file if requested
            if delete_drive_file:
                try:
                    self.drive.delete_file(doc_id, permanent=not soft_delete)
                    drive_file_deleted = True
                except Exception as e:
                    logger.warning(f"Failed to delete Drive file '{doc_id}': {e}")

            # Step 5: Delete related knowledge entries
            knowledge_deleted_count = self.rag.delete_knowledge_by_doc_id(doc_id, project)

            message_parts = [f"ドキュメント '{doc_id}' を削除しました。"]
            if catalog_deleted:
                message_parts.append("カタログエントリを削除しました。")
            if sheet_row_deleted:
                message_parts.append("Sheets目録から削除しました。")
            if drive_file_deleted:
                action = "ゴミ箱に移動" if soft_delete else "完全削除"
                message_parts.append(f"Driveファイルを{action}しました。")
            if knowledge_deleted_count > 0:
                message_parts.append(f"{knowledge_deleted_count}件の関連ナレッジを削除しました。")

            return DeleteDocumentResult(
                success=True,
                doc_id=doc_id,
                project=project,
                catalog_deleted=catalog_deleted,
                sheet_row_deleted=sheet_row_deleted,
                drive_file_deleted=drive_file_deleted,
                knowledge_deleted_count=knowledge_deleted_count,
                message=" ".join(message_parts),
            )

        except Exception as e:
            logger.error(f"Failed to delete document '{doc_id}': {e}")
            return DeleteDocumentResult(
                success=False,
                doc_id=doc_id,
                project=project,
                catalog_deleted=catalog_deleted,
                sheet_row_deleted=sheet_row_deleted,
                drive_file_deleted=drive_file_deleted,
                knowledge_deleted_count=knowledge_deleted_count,
                message=f"ドキュメントの削除に失敗しました: {e}",
            )

    def list_documents(
        self,
        project: Optional[str] = None,
        doc_type: Optional[str] = None,
        phase_task: Optional[str] = None,
        feature: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        user: Optional[str] = None,
    ) -> ListDocumentsResult:
        """List documents in a project with filtering and pagination.

        Args:
            project: Project ID (uses current if None)
            doc_type: Filter by document type
            phase_task: Filter by phase-task
            feature: Filter by feature
            limit: Maximum number of results
            offset: Skip first N results
            sort_by: Field to sort by (updated_at, name)
            sort_order: Sort order (asc, desc)
            user: User ID

        Returns:
            ListDocumentsResult
        """
        user = user or self.user_name

        # Get project ID
        if project:
            project_id = project
        else:
            project_id = self.project_tools.get_current_project_id(user)

        if not project_id:
            return ListDocumentsResult(
                success=False,
                message="プロジェクトが選択されていません。",
            )

        try:
            # Build where clause for RAG search
            where: dict = {
                "type": {"$eq": "catalog"},
                "project": {"$eq": project_id},
            }

            if doc_type:
                where["doc_type"] = {"$eq": doc_type}

            if phase_task:
                where["phase_task"] = {"$eq": phase_task}

            if feature:
                where["feature"] = {"$eq": feature}

            # Search with extra buffer for pagination
            result = self.rag.search_by_metadata(
                where=where,
                n_results=limit + offset + 100,  # Buffer for filtering
            )

            if not result.success:
                return ListDocumentsResult(
                    success=False,
                    message=f"ドキュメント一覧の取得に失敗しました: {result.message}",
                )

            # Convert to DocumentSummary objects
            documents = []
            for doc in result.documents:
                meta = doc.metadata
                documents.append(DocumentSummary(
                    doc_id=meta.get("doc_id", ""),
                    name=meta.get("name", ""),
                    doc_type=meta.get("doc_type", ""),
                    phase_task=meta.get("phase_task", ""),
                    feature=meta.get("feature", ""),
                    source=meta.get("source", ""),
                    url=meta.get("url", ""),
                    updated_at=meta.get("updated_at", ""),
                ))

            # Sort documents
            reverse = sort_order.lower() == "desc"
            if sort_by == "name":
                documents.sort(key=lambda d: d.name, reverse=reverse)
            else:  # default: updated_at
                documents.sort(key=lambda d: d.updated_at or "", reverse=reverse)

            # Apply pagination
            total_count = len(documents)
            documents = documents[offset:offset + limit]

            return ListDocumentsResult(
                success=True,
                documents=documents,
                total_count=total_count,
                offset=offset,
                limit=limit,
                message=f"{total_count}件のドキュメントが見つかりました。",
            )

        except Exception as e:
            logger.error(f"Failed to list documents: {e}")
            return ListDocumentsResult(
                success=False,
                message=f"ドキュメント一覧の取得に失敗しました: {e}",
            )
