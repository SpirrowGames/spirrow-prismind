"""Mock RAG client for testing."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from spirrow_prismind.integrations.rag_client import (
    RAGClient,
    RAGDocument,
    RAGOperationResult,
    RAGSearchResult,
)


class MockRAGClient(RAGClient):
    """In-memory mock RAG client for testing.

    Stores documents in memory and provides basic search functionality
    without requiring an actual RAG server.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        collection_name: str = "prismind",
        timeout: float = 30.0,
    ):
        # Don't call super().__init__() to avoid creating httpx client
        self.base_url = base_url
        self.collection_name = collection_name
        self.timeout = timeout

        # In-memory storage: collection -> doc_id -> document
        self._storage: dict[str, dict[str, RAGDocument]] = {}
        self._ensure_collection(collection_name)

    def _ensure_collection(self, collection: str) -> None:
        """Ensure a collection exists."""
        if collection not in self._storage:
            self._storage[collection] = {}

    def close(self):
        """No-op for mock client."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    # ===================
    # Document Operations
    # ===================

    def add_document(
        self,
        doc_id: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
        collection: Optional[str] = None,
    ) -> RAGOperationResult:
        """Add a document to the in-memory store."""
        collection_name = collection or self.collection_name
        self._ensure_collection(collection_name)

        self._storage[collection_name][doc_id] = RAGDocument(
            doc_id=doc_id,
            content=content,
            metadata=metadata or {},
            score=0.0,
        )

        return RAGOperationResult(
            success=True,
            doc_id=doc_id,
            message="Document added successfully",
        )

    def update_document(
        self,
        doc_id: str,
        content: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        collection: Optional[str] = None,
    ) -> RAGOperationResult:
        """Update a document in the in-memory store."""
        collection_name = collection or self.collection_name
        self._ensure_collection(collection_name)

        if doc_id not in self._storage[collection_name]:
            return RAGOperationResult(
                success=False,
                doc_id=doc_id,
                message="Document not found",
            )

        existing = self._storage[collection_name][doc_id]

        self._storage[collection_name][doc_id] = RAGDocument(
            doc_id=doc_id,
            content=content if content is not None else existing.content,
            metadata=metadata if metadata is not None else existing.metadata,
            score=0.0,
        )

        return RAGOperationResult(
            success=True,
            doc_id=doc_id,
            message="Document updated successfully",
        )

    def delete_document(
        self,
        doc_id: str,
        collection: Optional[str] = None,
    ) -> RAGOperationResult:
        """Delete a document from the in-memory store."""
        collection_name = collection or self.collection_name
        self._ensure_collection(collection_name)

        if doc_id in self._storage[collection_name]:
            del self._storage[collection_name][doc_id]
            return RAGOperationResult(
                success=True,
                doc_id=doc_id,
                message="Document deleted successfully",
            )

        return RAGOperationResult(
            success=False,
            doc_id=doc_id,
            message="Document not found",
        )

    def get_document(
        self,
        doc_id: str,
        collection: Optional[str] = None,
    ) -> Optional[RAGDocument]:
        """Get a document by ID."""
        collection_name = collection or self.collection_name
        self._ensure_collection(collection_name)

        return self._storage[collection_name].get(doc_id)

    # ===================
    # Search Operations
    # ===================

    def _calculate_similarity(self, query: str, content: str) -> float:
        """Calculate a simple similarity score.

        This is a simplified implementation for testing.
        Real RAG uses embeddings.
        """
        query_words = set(query.lower().split())
        content_words = set(content.lower().split())

        if not query_words:
            return 0.0

        intersection = query_words & content_words
        return len(intersection) / len(query_words)

    def _match_where_clause(self, metadata: dict, where: dict) -> bool:
        """Check if metadata matches a where clause."""
        for key, condition in where.items():
            if key == "$or":
                # OR condition: at least one must match
                if not any(self._match_where_clause(metadata, cond) for cond in condition):
                    return False
            elif key == "$and":
                # AND condition: all must match
                if not all(self._match_where_clause(metadata, cond) for cond in condition):
                    return False
            elif isinstance(condition, dict):
                # Operator condition
                for op, value in condition.items():
                    meta_value = metadata.get(key)
                    if op == "$eq" and meta_value != value:
                        return False
                    elif op == "$ne" and meta_value == value:
                        return False
                    elif op == "$in" and meta_value not in value:
                        return False
                    elif op == "$nin" and meta_value in value:
                        return False
            else:
                # Direct comparison
                if metadata.get(key) != condition:
                    return False

        return True

    def search(
        self,
        query: str,
        n_results: int = 10,
        where: Optional[dict[str, Any]] = None,
        collection: Optional[str] = None,
    ) -> RAGSearchResult:
        """Search for documents using simple text matching."""
        collection_name = collection or self.collection_name
        self._ensure_collection(collection_name)

        results = []

        for doc_id, doc in self._storage[collection_name].items():
            # Check where clause
            if where and not self._match_where_clause(doc.metadata, where):
                continue

            # Calculate similarity
            score = self._calculate_similarity(query, doc.content)

            if score > 0:
                results.append(RAGDocument(
                    doc_id=doc.doc_id,
                    content=doc.content,
                    metadata=doc.metadata,
                    score=score,
                ))

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        results = results[:n_results]

        return RAGSearchResult(
            success=True,
            documents=results,
            total_count=len(results),
            message="Search completed successfully",
        )

    def search_by_metadata(
        self,
        where: dict[str, Any],
        n_results: int = 100,
        collection: Optional[str] = None,
    ) -> RAGSearchResult:
        """Search for documents by metadata filter only."""
        collection_name = collection or self.collection_name
        self._ensure_collection(collection_name)

        results = []

        for doc_id, doc in self._storage[collection_name].items():
            if self._match_where_clause(doc.metadata, where):
                results.append(RAGDocument(
                    doc_id=doc.doc_id,
                    content=doc.content,
                    metadata=doc.metadata,
                    score=1.0,
                ))

                if len(results) >= n_results:
                    break

        return RAGSearchResult(
            success=True,
            documents=results,
            total_count=len(results),
            message="Search completed successfully",
        )

    # ===========================
    # Project Config Operations
    # ===========================

    def save_project_config(
        self,
        project_id: str,
        name: str,
        description: str,
        config_data: dict[str, Any],
    ) -> RAGOperationResult:
        """Save a project configuration."""
        doc_id = f"project:{project_id}"
        content = f"{name} - {description}"

        metadata = {
            "type": "project_config",
            "project_id": project_id,
            "name": name,
            "description": description,
            "updated_at": datetime.now().isoformat(),
            **config_data,
        }

        return self.add_document(doc_id, content, metadata)

    def get_project_config(self, project_id: str) -> Optional[RAGDocument]:
        """Get a project configuration."""
        return self.get_document(f"project:{project_id}")

    def list_projects(self) -> list[RAGDocument]:
        """List all project configurations."""
        result = self.search_by_metadata(
            where={"type": {"$eq": "project_config"}},
            n_results=100,
        )

        return result.documents if result.success else []

    def find_similar_projects(
        self,
        name: str,
        description: str,
        threshold: float = 0.7,
        exclude_project_id: Optional[str] = None,
    ) -> list[RAGDocument]:
        """Find projects similar to the given name/description."""
        query = f"{name} {description}".strip()

        result = self.search(
            query=query,
            n_results=10,
            where={"type": {"$eq": "project_config"}},
        )

        if not result.success:
            return []

        similar = []
        for doc in result.documents:
            if doc.score < threshold:
                continue

            doc_project_id = doc.metadata.get("project_id", "")
            if exclude_project_id and doc_project_id == exclude_project_id:
                continue

            similar.append(doc)

        return similar

    def delete_project_config(self, project_id: str) -> RAGOperationResult:
        """Delete a project configuration."""
        return self.delete_document(f"project:{project_id}")

    # =======================
    # Knowledge Operations
    # =======================

    def add_knowledge(
        self,
        content: str,
        category: str,
        tags: list[str],
        project: Optional[str] = None,
        source: Optional[str] = None,
    ) -> RAGOperationResult:
        """Add a knowledge entry."""
        doc_id = f"knowledge:{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

        metadata = {
            "type": "knowledge",
            "category": category,
            "tags": tags,
            "project": project or "",
            "source": source or "",
            "created_at": datetime.now().isoformat(),
        }

        return self.add_document(doc_id, content, metadata)

    def search_knowledge(
        self,
        query: str,
        category: Optional[str] = None,
        project: Optional[str] = None,
        tags: Optional[list[str]] = None,
        n_results: int = 5,
    ) -> RAGSearchResult:
        """Search for knowledge entries."""
        where: dict[str, Any] = {"type": {"$eq": "knowledge"}}

        if category:
            where["category"] = {"$eq": category}

        if project:
            where["$or"] = [
                {"project": {"$eq": project}},
                {"project": {"$eq": ""}},
            ]

        result = self.search(
            query=query,
            n_results=n_results * 2 if tags else n_results,
            where=where,
        )

        if not result.success:
            return result

        if tags:
            filtered = []
            for doc in result.documents:
                doc_tags = doc.metadata.get("tags", [])
                if all(tag in doc_tags for tag in tags):
                    filtered.append(doc)
                    if len(filtered) >= n_results:
                        break

            result.documents = filtered
            result.total_count = len(filtered)

        return result

    # =======================
    # Catalog Operations
    # =======================

    def add_catalog_entry(
        self,
        doc_id: str,
        name: str,
        doc_type: str,
        project: str,
        phase_task: str,
        metadata: dict[str, Any],
    ) -> RAGOperationResult:
        """Add a catalog entry."""
        catalog_id = f"catalog:{project}:{doc_id}"
        content = f"{name} {doc_type} {phase_task}"

        full_metadata = {
            "type": "catalog",
            "doc_id": doc_id,
            "name": name,
            "doc_type": doc_type,
            "project": project,
            "phase_task": phase_task,
            "updated_at": datetime.now().isoformat(),
            **metadata,
        }

        return self.add_document(catalog_id, content, full_metadata)

    def search_catalog(
        self,
        query: str,
        project: Optional[str] = None,
        doc_type: Optional[str] = None,
        phase_task: Optional[str] = None,
        n_results: int = 10,
    ) -> RAGSearchResult:
        """Search the catalog."""
        where: dict[str, Any] = {"type": {"$eq": "catalog"}}

        if project:
            where["project"] = {"$eq": project}

        if doc_type:
            where["doc_type"] = {"$eq": doc_type}

        if phase_task:
            where["phase_task"] = {"$eq": phase_task}

        return self.search(
            query=query,
            n_results=n_results,
            where=where,
        )

    def delete_catalog_entries_by_project(self, project: str) -> int:
        """Delete all catalog entries for a project."""
        result = self.search_by_metadata(
            where={
                "type": {"$eq": "catalog"},
                "project": {"$eq": project},
            },
            n_results=1000,
        )

        count = 0
        for doc in result.documents:
            if self.delete_document(doc.doc_id).success:
                count += 1

        return count

    # =======================
    # Test Helpers
    # =======================

    def clear_all(self) -> None:
        """Clear all data (useful for test setup/teardown)."""
        self._storage.clear()
        self._ensure_collection(self.collection_name)

    def get_all_documents(
        self,
        collection: Optional[str] = None,
    ) -> list[RAGDocument]:
        """Get all documents in a collection."""
        collection_name = collection or self.collection_name
        self._ensure_collection(collection_name)

        return list(self._storage[collection_name].values())
