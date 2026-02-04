"""Knowledge management tools for Spirrow-Prismind."""

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from ..integrations import MemoryClient, RAGClient
from ..models import (
    AddKnowledgeResult,
    DeleteKnowledgeResult,
    KnowledgeEntry,
    SearchKnowledgeResult,
    UpdateKnowledgeResult,
)
from .project_tools import ProjectTools

logger = logging.getLogger(__name__)


class KnowledgeTools:
    """Tools for knowledge management."""

    # Valid categories
    CATEGORIES = [
        "問題解決",
        "技術Tips",
        "ベストプラクティス",
        "落とし穴",
        "設計パターン",
        "その他",
        # Lifecycle management categories (used by Magickit)
        "milestone",
        "velocity",
        "quality_gate",
        "phase_transition",
        # Task management categories
        "task",
        "task_completion",
        "blocker",
        # Session management categories
        "decision",
        "session_insight",
        # Execution tracking
        "実装記録",
        "実装詳細",
    ]

    # Key for pending knowledge queue
    _PENDING_KNOWLEDGE_KEY = "prismind:pending_knowledge"

    def __init__(
        self,
        rag_client: RAGClient,
        project_tools: ProjectTools,
        memory_client: Optional[MemoryClient] = None,
        user_name: str = "default",
    ):
        """Initialize knowledge tools.

        Args:
            rag_client: RAG client for knowledge storage
            project_tools: Project tools for config access
            memory_client: Memory client for caching (optional)
            user_name: Default user ID
        """
        self.rag = rag_client
        self.project_tools = project_tools
        self.memory = memory_client
        self.user_name = user_name

        # Sync any pending knowledge if RAG is available
        if self.rag.is_available and self.memory:
            self._sync_pending_knowledge()

    def add_knowledge(
        self,
        content: str,
        category: str,
        project: Optional[str] = None,
        tags: Optional[list[str]] = None,
        source: Optional[str] = None,
        user: Optional[str] = None,
    ) -> AddKnowledgeResult:
        """Add a knowledge entry to RAG.

        Args:
            content: Knowledge content
            category: Category (問題解決/技術Tips/ベストプラクティス/落とし穴/etc.)
            project: Related project (None for general knowledge)
            tags: Search tags (auto-generated if None)
            source: Information source
            user: User ID

        Returns:
            AddKnowledgeResult
        """
        user = user or self.user_name

        # Validate category
        if category not in self.CATEGORIES:
            return AddKnowledgeResult(
                success=False,
                knowledge_id="",
                tags=[],
                message=f"無効なカテゴリです。有効なカテゴリ: {', '.join(self.CATEGORIES)}",
            )

        # Get current project if not specified
        if project is None:
            project = self.project_tools.get_current_project_id(user)

        # Auto-generate tags if not provided
        if tags is None:
            tags = self._generate_tags(content)

        # Check if RAG is available
        if not self.rag.is_available:
            # Queue for later sync
            pending_id = self._queue_pending_knowledge(
                content=content,
                category=category,
                tags=tags,
                project=project,
                source=source,
            )
            return AddKnowledgeResult(
                success=True,
                knowledge_id=pending_id,
                tags=tags,
                message="RAGサーバー接続不可のため、ローカルに保存しました。次回接続時に同期されます。",
            )

        # Add to RAG
        result = self.rag.add_knowledge(
            content=content,
            category=category,
            tags=tags,
            project=project,
            source=source,
        )

        if not result.success:
            return AddKnowledgeResult(
                success=False,
                knowledge_id="",
                tags=tags,
                message=f"知見の登録に失敗しました: {result.message}",
            )

        # Verify registration by checking if document exists
        doc = self.rag.get_document(result.doc_id)
        if doc is None:
            return AddKnowledgeResult(
                success=False,
                knowledge_id=result.doc_id,
                tags=tags,
                message="知見の登録に失敗しました（ドキュメントが見つかりません）",
            )

        # Cache in Memory Server for immediate search availability
        metadata = {
            "category": category,
            "tags": tags,
            "source": source or "",
        }
        if self.memory and self.memory.is_available:
            self.memory.cache_recent_knowledge(
                knowledge_id=result.doc_id,
                content=content,
                metadata=metadata,
                project=project,
            )

        return AddKnowledgeResult(
            success=True,
            knowledge_id=result.doc_id,
            tags=tags,
            message="知見を登録しました。",
        )

    def _queue_pending_knowledge(
        self,
        content: str,
        category: str,
        tags: list[str],
        project: Optional[str],
        source: Optional[str],
    ) -> str:
        """Queue knowledge for later sync when RAG is unavailable.

        Args:
            content: Knowledge content
            category: Category
            tags: Tags
            project: Project ID
            source: Source

        Returns:
            Pending knowledge ID
        """
        pending_id = f"pending:{uuid.uuid4().hex[:12]}"

        entry = {
            "pending_id": pending_id,
            "content": content,
            "category": category,
            "tags": tags,
            "project": project or "",
            "source": source or "",
            "queued_at": datetime.now().isoformat(),
        }

        if self.memory:
            # Get existing queue
            queue_entry = self.memory.get(self._PENDING_KNOWLEDGE_KEY)
            if queue_entry and queue_entry.value:
                queue = queue_entry.value
                if isinstance(queue, str):
                    try:
                        queue = json.loads(queue)
                    except json.JSONDecodeError:
                        queue = []
            else:
                queue = []

            # Add to queue
            queue.append(entry)
            self.memory.set(self._PENDING_KNOWLEDGE_KEY, queue)

            # Also cache for immediate search
            self.memory.cache_recent_knowledge(
                knowledge_id=pending_id,
                content=content,
                metadata={"category": category, "tags": tags, "source": source or ""},
                project=project,
            )

        return pending_id

    def _sync_pending_knowledge(self) -> int:
        """Sync pending knowledge entries to RAG.

        Returns:
            Number of entries synced
        """
        if not self.memory or not self.rag.is_available:
            return 0

        # Get queue
        queue_entry = self.memory.get(self._PENDING_KNOWLEDGE_KEY)
        if not queue_entry or not queue_entry.value:
            return 0

        queue = queue_entry.value
        if isinstance(queue, str):
            try:
                queue = json.loads(queue)
            except json.JSONDecodeError:
                return 0

        if not queue:
            return 0

        synced = 0
        failed = []

        for entry in queue:
            try:
                result = self.rag.add_knowledge(
                    content=entry["content"],
                    category=entry["category"],
                    tags=entry["tags"],
                    project=entry.get("project") or None,
                    source=entry.get("source"),
                )

                if result.success:
                    synced += 1
                    # Update cache with real ID
                    pending_id = entry.get("pending_id", "")
                    if pending_id:
                        self.memory.clear_recent_knowledge(pending_id)
                    self.memory.cache_recent_knowledge(
                        knowledge_id=result.doc_id,
                        content=entry["content"],
                        metadata={
                            "category": entry["category"],
                            "tags": entry["tags"],
                            "source": entry.get("source", ""),
                        },
                        project=entry.get("project") or None,
                    )
                else:
                    failed.append(entry)
            except Exception as e:
                logger.warning(f"Failed to sync pending knowledge: {e}")
                failed.append(entry)

        # Update queue with failed entries only
        if failed:
            self.memory.set(self._PENDING_KNOWLEDGE_KEY, failed)
        else:
            self.memory.delete(self._PENDING_KNOWLEDGE_KEY)

        if synced > 0:
            logger.info(f"Synced {synced} pending knowledge entries to RAG")

        return synced

    def get_pending_count(self) -> int:
        """Get count of pending knowledge entries.

        Returns:
            Number of pending entries
        """
        if not self.memory:
            return 0

        queue_entry = self.memory.get(self._PENDING_KNOWLEDGE_KEY)
        if not queue_entry or not queue_entry.value:
            return 0

        queue = queue_entry.value
        if isinstance(queue, str):
            try:
                queue = json.loads(queue)
            except json.JSONDecodeError:
                return 0

        return len(queue) if isinstance(queue, list) else 0

    def search_knowledge(
        self,
        query: str,
        category: Optional[str] = None,
        project: Optional[str] = None,
        tags: Optional[list[str]] = None,
        include_general: bool = True,
        limit: int = 5,
        user: Optional[str] = None,
    ) -> SearchKnowledgeResult:
        """Search for knowledge entries.

        Args:
            query: Search query
            category: Filter by category
            project: Filter by project (None for all)
            tags: Filter by tags (AND condition)
            include_general: Include general (non-project) knowledge
            limit: Maximum results
            user: User ID

        Returns:
            SearchKnowledgeResult
        """
        user = user or self.user_name

        # Get current project if not specified
        search_project = project
        if search_project is None:
            search_project = self.project_tools.get_current_project_id(user)

        # If RAG is unavailable, search from local cache only
        if not self.rag.is_available:
            return self._search_from_cache(
                query=query,
                category=category,
                project=search_project,
                tags=tags,
                include_general=include_general,
                limit=limit,
            )

        # Search RAG with project filter
        # RAG will include general knowledge (empty project) via $or clause when project is specified
        result = self.rag.search_knowledge(
            query=query,
            category=category,
            project=search_project,  # Always pass project for proper filtering
            tags=tags,
            n_results=limit * 2 if include_general else limit,  # Get more results if including general
        )

        if not result.success:
            # Fall back to cache on RAG error
            return self._search_from_cache(
                query=query,
                category=category,
                project=search_project,
                tags=tags,
                include_general=include_general,
                limit=limit,
            )
        
        # Convert to KnowledgeEntry
        knowledge = []
        for doc in result.documents:
            meta = doc.metadata

            # Parse created_at
            created_at_str = meta.get("created_at", "")

            # Parse tags (handle both list and JSON string)
            doc_tags = meta.get("tags", [])
            if isinstance(doc_tags, str):
                try:
                    doc_tags = json.loads(doc_tags)
                except json.JSONDecodeError:
                    # Try comma-separated
                    doc_tags = [t.strip() for t in doc_tags.split(",") if t.strip()]

            knowledge.append(KnowledgeEntry(
                knowledge_id=doc.doc_id,
                content=doc.content,
                category=meta.get("category", ""),
                project=meta.get("project"),
                tags=doc_tags if isinstance(doc_tags, list) else [],
                source=meta.get("source"),
                created_at=created_at_str,
                relevance_score=doc.score,
            ))

        # Filter by project if needed
        if search_project:
            if include_general:
                # Keep both project-specific and general
                filtered = [
                    k for k in knowledge
                    if k.project == search_project or k.project == "" or k.project is None
                ]
            else:
                # Keep only project-specific
                filtered = [k for k in knowledge if k.project == search_project]
            knowledge = filtered

        # Merge with cached recent knowledge (for immediate availability)
        existing_ids = {k.knowledge_id for k in knowledge}
        if self.memory and self.memory.is_available:
            cached = self.memory.get_recent_knowledge(
                project=search_project if not include_general else None,
                limit=limit,
            )
            for entry in cached:
                kid = entry.get("knowledge_id", "")
                if kid and kid not in existing_ids:
                    # Simple text matching for cached entries
                    content = entry.get("content", "")
                    query_lower = query.lower()
                    if query_lower in content.lower():
                        meta = entry.get("metadata", {})
                        # Apply category filter
                        if category and meta.get("category") != category:
                            continue
                        # Apply tags filter
                        if tags:
                            entry_tags = meta.get("tags", [])
                            if not all(t in entry_tags for t in tags):
                                continue

                        knowledge.insert(0, KnowledgeEntry(
                            knowledge_id=kid,
                            content=content,
                            category=meta.get("category", ""),
                            project=entry.get("project"),
                            tags=meta.get("tags", []),
                            source=meta.get("source"),
                            created_at=entry.get("cached_at", ""),
                            relevance_score=1.0,  # High score for recent cache
                        ))
                        existing_ids.add(kid)

        # Apply limit
        knowledge = knowledge[:limit]

        return SearchKnowledgeResult(
            success=True,
            total_count=len(knowledge),
            knowledge=knowledge,
            message=f"{len(knowledge)} 件の知見が見つかりました。",
        )

    def _search_from_cache(
        self,
        query: str,
        category: Optional[str],
        project: Optional[str],
        tags: Optional[list[str]],
        include_general: bool,
        limit: int,
    ) -> SearchKnowledgeResult:
        """Search knowledge from local cache only.

        Used when RAG is unavailable.

        Args:
            query: Search query
            category: Category filter
            project: Project filter
            tags: Tags filter
            include_general: Include general knowledge
            limit: Maximum results

        Returns:
            SearchKnowledgeResult
        """
        if not self.memory:
            return SearchKnowledgeResult(
                success=False,
                total_count=0,
                knowledge=[],
                message="RAGサーバー接続不可、かつローカルキャッシュもありません。",
            )

        # Get cached entries
        cached = self.memory.get_recent_knowledge(
            project=None if include_general else project,
            limit=limit * 3,  # Get more for filtering
        )

        knowledge = []
        query_lower = query.lower()

        for entry in cached:
            # Simple text matching
            content = entry.get("content", "")
            if query_lower not in content.lower():
                continue

            meta = entry.get("metadata", {})
            entry_project = entry.get("project", "")

            # Apply project filter
            if project:
                if include_general:
                    if entry_project not in (project, "", None):
                        continue
                else:
                    if entry_project != project:
                        continue

            # Apply category filter
            if category and meta.get("category") != category:
                continue

            # Apply tags filter
            if tags:
                entry_tags = meta.get("tags", [])
                if isinstance(entry_tags, str):
                    try:
                        entry_tags = json.loads(entry_tags)
                    except json.JSONDecodeError:
                        entry_tags = []
                if not all(t in entry_tags for t in tags):
                    continue

            kid = entry.get("knowledge_id", "")
            entry_tags = meta.get("tags", [])
            if isinstance(entry_tags, str):
                try:
                    entry_tags = json.loads(entry_tags)
                except json.JSONDecodeError:
                    entry_tags = []

            knowledge.append(
                KnowledgeEntry(
                    knowledge_id=kid,
                    content=content,
                    category=meta.get("category", ""),
                    project=entry_project if entry_project else None,
                    tags=entry_tags if isinstance(entry_tags, list) else [],
                    source=meta.get("source"),
                    created_at=entry.get("cached_at", ""),
                    relevance_score=1.0,
                )
            )

            if len(knowledge) >= limit:
                break

        pending_count = self.get_pending_count()
        warning = ""
        if pending_count > 0:
            warning = f" ({pending_count} 件の同期待ちエントリあり)"

        return SearchKnowledgeResult(
            success=True,
            total_count=len(knowledge),
            knowledge=knowledge,
            message=f"ローカルキャッシュから {len(knowledge)} 件の知見が見つかりました。"
            f"（RAGサーバー接続不可）{warning}",
        )

    def _generate_tags(self, content: str) -> list[str]:
        """Generate tags from content.
        
        Args:
            content: Knowledge content
            
        Returns:
            List of tags
        """
        tags = []
        
        # Simple tag extraction
        # In production, this could use NLP or LLM
        
        # Extract potential keywords
        words = content.split()
        
        # Look for technical terms (simple heuristics)
        for word in words:
            word = word.strip(",.;:()[]{}\"'")
            
            # Skip short words
            if len(word) < 3:
                continue
            
            # Skip common words
            common_words = {
                "the", "and", "for", "with", "this", "that", "from",
                "have", "will", "are", "was", "were", "been", "being",
                "です", "ます", "した", "する", "ある", "いる", "なる",
                "という", "ため", "こと", "もの", "これ", "それ",
            }
            if word.lower() in common_words:
                continue
            
            # Technical indicators
            if any([
                word.startswith("U"),  # UE, Unity, etc.
                word.endswith("++"),
                word.endswith("API"),
                "_" in word,  # snake_case
                word[0].isupper() and any(c.isupper() for c in word[1:]),  # CamelCase
            ]):
                tags.append(word)
        
        # Deduplicate and limit
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag.lower() not in seen:
                seen.add(tag.lower())
                unique_tags.append(tag)
                if len(unique_tags) >= 10:
                    break
        
        return unique_tags

    def get_categories(self) -> list[str]:
        """Get available knowledge categories.
        
        Returns:
            List of category names
        """
        return self.CATEGORIES.copy()

    def delete_knowledge(
        self,
        knowledge_id: str,
        project: Optional[str] = None,
        user: Optional[str] = None,
    ) -> DeleteKnowledgeResult:
        """Delete a knowledge entry.

        Args:
            knowledge_id: Knowledge entry ID
            project: Project name for verification (optional safety check)
            user: User ID

        Returns:
            DeleteKnowledgeResult
        """
        user = user or self.user_name

        # Check if RAG is available
        if not self.rag.is_available:
            return DeleteKnowledgeResult(
                success=False,
                knowledge_id=knowledge_id,
                message="RAGサーバーに接続できません。",
            )

        # Get existing document to verify it exists and check project
        doc = self.rag.get_document(knowledge_id)
        if doc is None:
            return DeleteKnowledgeResult(
                success=False,
                knowledge_id=knowledge_id,
                message=f"知見が見つかりません: {knowledge_id}",
            )

        # Get document's project from metadata
        doc_project = doc.metadata.get("project", "") if doc.metadata else ""

        # Verify project if specified (safety check)
        if project is not None and doc_project and doc_project != project:
            return DeleteKnowledgeResult(
                success=False,
                knowledge_id=knowledge_id,
                project=doc_project,
                message=f"プロジェクトが一致しません。知見のプロジェクト: {doc_project}, 指定されたプロジェクト: {project}",
            )

        # Delete from RAG
        rag_result = self.rag.delete_document(knowledge_id)
        rag_deleted = rag_result.success

        # Clear from cache
        cache_cleared = False
        if self.memory and self.memory.is_available:
            try:
                self.memory.clear_recent_knowledge(knowledge_id)
                cache_cleared = True
            except Exception as e:
                logger.warning(f"Failed to clear knowledge from cache: {e}")

        if not rag_deleted:
            return DeleteKnowledgeResult(
                success=False,
                knowledge_id=knowledge_id,
                project=doc_project,
                rag_deleted=False,
                cache_cleared=cache_cleared,
                message=f"知見の削除に失敗しました: {rag_result.message}",
            )

        return DeleteKnowledgeResult(
            success=True,
            knowledge_id=knowledge_id,
            project=doc_project,
            rag_deleted=True,
            cache_cleared=cache_cleared,
            message="知見を削除しました。",
        )

    def update_knowledge(
        self,
        knowledge_id: str,
        content: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
        source: Optional[str] = None,
    ) -> UpdateKnowledgeResult:
        """Update an existing knowledge entry.

        Args:
            knowledge_id: Knowledge entry ID to update
            content: New content (None to keep existing)
            category: New category (None to keep existing)
            tags: New tags (None to keep existing)
            source: New source (None to keep existing)

        Returns:
            UpdateKnowledgeResult
        """
        # Get existing document
        doc = self.rag.get_document(knowledge_id)
        if doc is None:
            return UpdateKnowledgeResult(
                success=False,
                knowledge_id=knowledge_id,
                updated_fields=[],
                message=f"知見が見つかりません: {knowledge_id}",
            )

        # Validate category if provided
        if category is not None and category not in self.CATEGORIES:
            return UpdateKnowledgeResult(
                success=False,
                knowledge_id=knowledge_id,
                updated_fields=[],
                message=f"無効なカテゴリです。有効なカテゴリ: {', '.join(self.CATEGORIES)}",
            )

        # Build updated metadata
        existing_meta = doc.metadata
        updated_fields = []

        new_content = content
        if content is not None and content != doc.content:
            updated_fields.append("content")
        else:
            new_content = None  # Don't update if unchanged

        new_metadata = {}
        if category is not None and category != existing_meta.get("category"):
            new_metadata["category"] = category
            updated_fields.append("category")

        if tags is not None:
            existing_tags = existing_meta.get("tags", [])
            if isinstance(existing_tags, str):
                try:
                    existing_tags = json.loads(existing_tags)
                except json.JSONDecodeError:
                    existing_tags = []
            if set(tags) != set(existing_tags):
                new_metadata["tags"] = tags
                updated_fields.append("tags")

        if source is not None and source != existing_meta.get("source"):
            new_metadata["source"] = source
            updated_fields.append("source")

        # Check if anything to update
        if not updated_fields:
            return UpdateKnowledgeResult(
                success=True,
                knowledge_id=knowledge_id,
                updated_fields=[],
                message="更新する項目がありません。",
            )

        # Merge with existing metadata
        if new_metadata:
            full_metadata = {**existing_meta, **new_metadata}
        else:
            full_metadata = None

        # Update in RAG
        result = self.rag.update_document(
            doc_id=knowledge_id,
            content=new_content,
            metadata=full_metadata,
        )

        if not result.success:
            return UpdateKnowledgeResult(
                success=False,
                knowledge_id=knowledge_id,
                updated_fields=[],
                message=f"知見の更新に失敗しました: {result.message}",
            )

        # Update cache if Memory Server available
        if self.memory and self.memory.is_available:
            final_content = content if content is not None else doc.content
            final_metadata = {
                "category": category if category is not None else existing_meta.get("category", ""),
                "tags": tags if tags is not None else existing_meta.get("tags", []),
                "source": source if source is not None else existing_meta.get("source", ""),
            }
            project = existing_meta.get("project", "")
            self.memory.cache_recent_knowledge(
                knowledge_id=knowledge_id,
                content=final_content,
                metadata=final_metadata,
                project=project if project else None,
            )

        return UpdateKnowledgeResult(
            success=True,
            knowledge_id=knowledge_id,
            updated_fields=updated_fields,
            message=f"知見を更新しました: {', '.join(updated_fields)}",
        )
