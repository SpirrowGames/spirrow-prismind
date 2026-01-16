"""Knowledge management tools for Spirrow-Prismind."""

import json
import logging
from typing import Optional

from ..integrations import MemoryClient, RAGClient
from ..models import (
    AddKnowledgeResult,
    KnowledgeEntry,
    SearchKnowledgeResult,
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
    ]

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
            return SearchKnowledgeResult(
                success=False,
                total_count=0,
                knowledge=[],
                message=f"検索に失敗しました: {result.message}",
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
    ) -> bool:
        """Delete a knowledge entry.
        
        Args:
            knowledge_id: Knowledge entry ID
            
        Returns:
            True if successful
        """
        result = self.rag.delete_document(knowledge_id)
        return result.success
