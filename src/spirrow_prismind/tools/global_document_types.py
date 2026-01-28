"""Global document type storage.

Manages document types that are shared across all projects.
Storage location: ~/.prismind_global_doc_types.json

Supports RAG-based semantic search for finding similar document types.
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ..models.document import DocumentType

if TYPE_CHECKING:
    from ..integrations.rag_client import RAGClient

logger = logging.getLogger(__name__)

# Default storage path
DEFAULT_STORAGE_PATH = Path.home() / ".prismind_global_doc_types.json"

# Default similarity threshold for semantic matching
DEFAULT_SIMILARITY_THRESHOLD = 0.75


class GlobalDocumentTypeStorage:
    """Global document type storage with RAG-based semantic search.

    Stores document types that are shared across all projects in a JSON file.
    Optionally syncs to RAG for semantic search capabilities.
    """

    _instance: Optional["GlobalDocumentTypeStorage"] = None
    _storage_path: Path
    _types: dict[str, DocumentType]
    _rag: Optional["RAGClient"]

    def __new__(
        cls,
        storage_path: Optional[Path] = None,
        rag_client: Optional["RAGClient"] = None,
    ) -> "GlobalDocumentTypeStorage":
        """Get singleton instance.

        Args:
            storage_path: Path to JSON storage file
            rag_client: Optional RAGClient for semantic search
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._storage_path = storage_path or DEFAULT_STORAGE_PATH
            cls._instance._types = {}
            cls._instance._rag = rag_client
            cls._instance._load()
            # Sync to RAG on first initialization
            if rag_client and rag_client.is_available:
                cls._instance._sync_to_rag()
        elif rag_client is not None and cls._instance._rag is None:
            # Update RAG client if provided later
            cls._instance._rag = rag_client
            if rag_client.is_available:
                cls._instance._sync_to_rag()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None

    def set_rag_client(self, rag_client: "RAGClient") -> None:
        """Set the RAG client and sync existing types.

        Args:
            rag_client: RAGClient instance
        """
        self._rag = rag_client
        if rag_client and rag_client.is_available:
            self._sync_to_rag()

    def _sync_to_rag(self) -> None:
        """Sync all document types to RAG for semantic search."""
        if not self._rag or not self._rag.is_available:
            return

        types_data = [
            {
                "type_id": dt.type_id,
                "name": dt.name,
                "description": dt.description,
                "folder_name": dt.folder_name,
            }
            for dt in self._types.values()
        ]

        if types_data:
            result = self._rag.sync_document_types(types_data)
            logger.info(
                f"Synced {result['synced']} document types to RAG "
                f"({result['failed']} failed)"
            )

    def _load(self) -> None:
        """Load types from storage file."""
        if not self._storage_path.exists():
            logger.debug(f"Global doc types file not found: {self._storage_path}")
            self._types = {}
            return

        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._types = {}
            for type_id, type_data in data.items():
                # Ensure is_global is set
                type_data["is_global"] = True
                self._types[type_id] = DocumentType.from_dict(type_data)

            logger.info(f"Loaded {len(self._types)} global document types")

        except Exception as e:
            logger.error(f"Failed to load global doc types: {e}")
            self._types = {}

    def _save(self) -> None:
        """Save types to storage file."""
        try:
            data = {
                type_id: doc_type.to_dict()
                for type_id, doc_type in self._types.items()
            }

            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.debug(f"Saved {len(self._types)} global document types")

        except Exception as e:
            logger.error(f"Failed to save global doc types: {e}")
            raise

    def get_all(self) -> list[DocumentType]:
        """Get all global document types.

        Returns:
            List of all registered global document types.
        """
        return list(self._types.values())

    def get(self, type_id: str) -> Optional[DocumentType]:
        """Get a specific document type by ID.

        Args:
            type_id: Document type ID.

        Returns:
            DocumentType if found, None otherwise.
        """
        return self._types.get(type_id)

    def exists(self, type_id: str) -> bool:
        """Check if a document type exists.

        Args:
            type_id: Document type ID.

        Returns:
            True if type exists, False otherwise.
        """
        return type_id in self._types

    def register(self, doc_type: DocumentType) -> bool:
        """Register a new global document type.

        Args:
            doc_type: Document type to register.

        Returns:
            True if registered, False if type_id already exists.
        """
        if doc_type.type_id in self._types:
            logger.warning(f"Global document type already exists: {doc_type.type_id}")
            return False

        # Ensure is_global is set
        doc_type.is_global = True
        self._types[doc_type.type_id] = doc_type
        self._save()

        # Also save to RAG for semantic search
        if self._rag and self._rag.is_available:
            self._rag.save_document_type(
                type_id=doc_type.type_id,
                name=doc_type.name,
                description=doc_type.description,
                folder_name=doc_type.folder_name,
            )

        logger.info(f"Registered global document type: {doc_type.type_id}")
        return True

    def update(self, doc_type: DocumentType) -> bool:
        """Update an existing global document type.

        Args:
            doc_type: Document type with updated values.

        Returns:
            True if updated, False if type_id doesn't exist.
        """
        if doc_type.type_id not in self._types:
            logger.warning(f"Global document type not found: {doc_type.type_id}")
            return False

        # Ensure is_global is set
        doc_type.is_global = True
        self._types[doc_type.type_id] = doc_type
        self._save()

        logger.info(f"Updated global document type: {doc_type.type_id}")
        return True

    def delete(self, type_id: str) -> bool:
        """Delete a global document type.

        Args:
            type_id: Document type ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        if type_id not in self._types:
            logger.warning(f"Global document type not found: {type_id}")
            return False

        del self._types[type_id]
        self._save()

        # Also delete from RAG
        if self._rag and self._rag.is_available:
            self._rag.delete_document_type_from_rag(type_id)

        logger.info(f"Deleted global document type: {type_id}")
        return True

    def reload(self) -> None:
        """Reload types from storage file."""
        self._load()

    def find_similar(
        self,
        query: str,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> Optional[DocumentType]:
        """Find a document type semantically similar to the query.

        Uses RAG semantic search if available, falls back to local string matching.

        Args:
            query: Search query (type_id, name, or description)
            threshold: Minimum similarity score (0.0-1.0)

        Returns:
            Most similar DocumentType if found above threshold, None otherwise.
        """
        # Try RAG semantic search first
        if self._rag and self._rag.is_available:
            matches = self._rag.find_similar_document_types(
                query=query,
                threshold=threshold,
                limit=1,
            )
            if matches:
                type_id = matches[0].metadata.get("type_id")
                if type_id and type_id in self._types:
                    logger.debug(
                        f"RAG semantic match: '{query}' -> '{type_id}' "
                        f"(score: {matches[0].score:.3f})"
                    )
                    return self._types[type_id]

        # Fallback to local string matching
        return self._find_similar_local(query)

    def _find_similar_local(self, query: str) -> Optional[DocumentType]:
        """Find similar document type using local string matching.

        This is a fallback when RAG is not available.

        Args:
            query: Search query

        Returns:
            DocumentType if exact/close match found, None otherwise.
        """
        query_lower = query.lower().replace("-", "_").replace(" ", "_")

        # 1. Exact type_id match
        if query_lower in self._types:
            return self._types[query_lower]

        # 2. Exact name match (case-insensitive)
        for doc_type in self._types.values():
            if doc_type.name.lower() == query_lower:
                return doc_type

        # 3. Prefix/substring match on type_id
        for type_id, doc_type in self._types.items():
            # Check if query is prefix of type_id or vice versa
            if type_id.startswith(query_lower) or query_lower.startswith(type_id):
                logger.debug(f"Local prefix match: '{query}' -> '{type_id}'")
                return doc_type

        # 4. Check if query contains type_id or vice versa
        for type_id, doc_type in self._types.items():
            if type_id in query_lower or query_lower in type_id:
                logger.debug(f"Local substring match: '{query}' -> '{type_id}'")
                return doc_type

        # No match found
        return None

    def find_similar_with_score(
        self,
        query: str,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> tuple[Optional[DocumentType], float]:
        """Find similar document type with similarity score.

        Args:
            query: Search query
            threshold: Minimum similarity score

        Returns:
            Tuple of (DocumentType, score) or (None, 0.0) if not found.
        """
        # Try RAG semantic search first
        if self._rag and self._rag.is_available:
            matches = self._rag.find_similar_document_types(
                query=query,
                threshold=threshold,
                limit=1,
            )
            if matches:
                type_id = matches[0].metadata.get("type_id")
                if type_id and type_id in self._types:
                    return self._types[type_id], matches[0].score

        # Fallback to local matching (with synthetic score)
        match = self._find_similar_local(query)
        if match:
            # Return synthetic score for local matches
            return match, 0.8  # Assume 0.8 similarity for local matches

        return None, 0.0
