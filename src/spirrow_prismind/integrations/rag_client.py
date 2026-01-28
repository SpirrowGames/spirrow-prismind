"""RAG (Retrieval-Augmented Generation) server client for knowledge management."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import httpx

from .retry import RETRYABLE_EXCEPTIONS, with_retry

logger = logging.getLogger(__name__)

# Collection name for document types (separate from main knowledge collection)
DOCUMENT_TYPES_COLLECTION = "document_types"

# Default similarity threshold for document type matching
DEFAULT_SIMILARITY_THRESHOLD = 0.75


@dataclass
class RAGDocument:
    """A document stored in RAG."""
    doc_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0  # Relevance score from search


@dataclass
class RAGSearchResult:
    """Result of a RAG search."""
    success: bool
    documents: list[RAGDocument] = field(default_factory=list)
    total_count: int = 0
    message: str = ""


@dataclass
class RAGOperationResult:
    """Result of a RAG operation (add/update/delete)."""
    success: bool
    doc_id: str = ""
    message: str = ""


class RAGClient:
    """Client for RAG server operations.

    Assumes a ChromaDB-compatible REST API.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        collection_name: str = "prismind",
        timeout: float = 30.0,
        connect_timeout: float = 3.0,
    ):
        """Initialize the RAG client.

        Args:
            base_url: RAG server URL
            collection_name: Default collection name
            timeout: Request timeout in seconds
            connect_timeout: Connection check timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.collection_name = collection_name
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
        self._available = self._check_connection(connect_timeout)

    def _check_connection(self, timeout: float) -> bool:
        """Check if the RAG server is available.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            True if server is available, False otherwise
        """
        try:
            response = httpx.get(
                f"{self.base_url}/api/v1/heartbeat",
                timeout=timeout,
            )
            if response.status_code == 200:
                logger.info(f"RAG server connected: {self.base_url}")
                # Try to verify collection exists
                self._ensure_collection_exists()
                return True
            else:
                logger.warning(f"RAG server returned status {response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"RAG server not available at {self.base_url}: {e}")
            return False

    def _ensure_collection_exists(self):
        """Ensure the default collection exists, create if needed."""
        try:
            # Try to get collection info
            response = self._client.get(
                f"{self.base_url}/api/v1/collections/{self.collection_name}",
            )
            if response.status_code == 200:
                logger.debug(f"Collection '{self.collection_name}' exists")
            elif response.status_code == 404:
                # Try to create the collection
                logger.info(f"Creating collection '{self.collection_name}'")
                create_response = self._client.post(
                    f"{self.base_url}/api/v1/collections",
                    json={"name": self.collection_name},
                )
                if create_response.status_code in (200, 201):
                    logger.info(f"Created collection '{self.collection_name}'")
                else:
                    logger.warning(
                        f"Failed to create collection: {create_response.status_code} - {create_response.text}"
                    )
        except Exception as e:
            logger.warning(f"Could not verify/create collection: {e}")

    @property
    def is_available(self) -> bool:
        """Check if the RAG server is available."""
        return self._available

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """Make an HTTP request to the RAG server with retry.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint
            json_data: JSON body data
            params: Query parameters

        Returns:
            Response JSON

        Raises:
            httpx.HTTPError: If the request fails after retries
        """
        url = f"{self.base_url}{endpoint}"

        # Use retry wrapper for transient network errors
        @with_retry(
            max_retries=3,
            base_delay=0.5,
            max_delay=10.0,
            retryable_exceptions=RETRYABLE_EXCEPTIONS,
        )
        def do_request() -> httpx.Response:
            return self._client.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
            )

        response = do_request()
        response.raise_for_status()

        return response.json()

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
        """Add a document to the RAG store.

        Args:
            doc_id: Unique document ID
            content: Document content (used for embedding)
            metadata: Additional metadata
            collection: Collection name (uses default if None)

        Returns:
            RAGOperationResult
        """
        try:
            data = {
                "ids": [doc_id],
                "documents": [content],
                "metadatas": [metadata or {}],
            }

            collection_name = collection or self.collection_name
            logger.debug(f"Adding document to RAG: id={doc_id}, collection={collection_name}")
            self._make_request(
                "POST",
                f"/api/v1/collections/{collection_name}/add",
                json_data=data,
            )

            return RAGOperationResult(
                success=True,
                doc_id=doc_id,
                message="Document added successfully",
            )
        except httpx.HTTPStatusError as e:
            # Log detailed error for HTTP status errors
            response_text = ""
            try:
                response_text = e.response.text
            except Exception:
                pass
            logger.error(
                f"Failed to add document '{doc_id}': HTTP {e.response.status_code} - {response_text}"
            )
            return RAGOperationResult(
                success=False,
                doc_id=doc_id,
                message=f"HTTP {e.response.status_code}: {response_text or str(e)}",
            )
        except httpx.HTTPError as e:
            logger.error(f"Failed to add document '{doc_id}': {e}")
            return RAGOperationResult(
                success=False,
                doc_id=doc_id,
                message=str(e),
            )

    def update_document(
        self,
        doc_id: str,
        content: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        collection: Optional[str] = None,
    ) -> RAGOperationResult:
        """Update a document in the RAG store.
        
        Args:
            doc_id: Document ID to update
            content: New content (None to keep existing)
            metadata: New metadata (None to keep existing)
            collection: Collection name (uses default if None)
            
        Returns:
            RAGOperationResult
        """
        try:
            data = {"ids": [doc_id]}
            
            if content is not None:
                data["documents"] = [content]
            
            if metadata is not None:
                data["metadatas"] = [metadata]
            
            collection_name = collection or self.collection_name
            self._make_request(
                "POST",
                f"/api/v1/collections/{collection_name}/update",
                json_data=data,
            )
            
            return RAGOperationResult(
                success=True,
                doc_id=doc_id,
                message="Document updated successfully",
            )
        except httpx.HTTPError as e:
            logger.error(f"Failed to update document '{doc_id}': {e}")
            return RAGOperationResult(
                success=False,
                doc_id=doc_id,
                message=str(e),
            )

    def upsert_document(
        self,
        doc_id: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
        collection: Optional[str] = None,
    ) -> RAGOperationResult:
        """Insert or update a document in the RAG store.

        If the document exists, it will be updated. Otherwise, it will be added.

        Args:
            doc_id: Document ID
            content: Document content
            metadata: Document metadata
            collection: Collection name (uses default if None)

        Returns:
            RAGOperationResult
        """
        # Check if document exists
        existing = self.get_document(doc_id, collection)

        if existing:
            # Update existing document
            logger.debug(f"Document exists, updating: id={doc_id}")
            return self.update_document(doc_id, content, metadata, collection)
        else:
            # Add new document
            logger.debug(f"Document does not exist, adding: id={doc_id}")
            return self.add_document(doc_id, content, metadata, collection)

    def delete_document(
        self,
        doc_id: str,
        collection: Optional[str] = None,
    ) -> RAGOperationResult:
        """Delete a document from the RAG store.
        
        Args:
            doc_id: Document ID to delete
            collection: Collection name (uses default if None)
            
        Returns:
            RAGOperationResult
        """
        try:
            collection_name = collection or self.collection_name
            self._make_request(
                "POST",
                f"/api/v1/collections/{collection_name}/delete",
                json_data={"ids": [doc_id]},
            )
            
            return RAGOperationResult(
                success=True,
                doc_id=doc_id,
                message="Document deleted successfully",
            )
        except httpx.HTTPError as e:
            logger.error(f"Failed to delete document '{doc_id}': {e}")
            return RAGOperationResult(
                success=False,
                doc_id=doc_id,
                message=str(e),
            )

    def get_document(
        self,
        doc_id: str,
        collection: Optional[str] = None,
    ) -> Optional[RAGDocument]:
        """Get a document by ID.
        
        Args:
            doc_id: Document ID
            collection: Collection name (uses default if None)
            
        Returns:
            RAGDocument if found, None otherwise
        """
        try:
            collection_name = collection or self.collection_name
            result = self._make_request(
                "POST",
                f"/api/v1/collections/{collection_name}/get",
                json_data={"ids": [doc_id]},
            )
            
            ids = result.get("ids", [])
            if not ids:
                return None
            
            documents = result.get("documents", [])
            metadatas = result.get("metadatas", [])
            
            return RAGDocument(
                doc_id=ids[0] if ids else doc_id,
                content=documents[0] if documents else "",
                metadata=metadatas[0] if metadatas else {},
            )
        except httpx.HTTPError as e:
            logger.error(f"Failed to get document '{doc_id}': {e}")
            return None

    # ===================
    # Search Operations
    # ===================

    def search(
        self,
        query: str,
        n_results: int = 10,
        where: Optional[dict[str, Any]] = None,
        collection: Optional[str] = None,
    ) -> RAGSearchResult:
        """Search for documents using semantic similarity.
        
        Args:
            query: Search query (will be embedded)
            n_results: Maximum number of results
            where: Metadata filter (ChromaDB where clause)
            collection: Collection name (uses default if None)
            
        Returns:
            RAGSearchResult
        """
        try:
            data = {
                "query_texts": [query],
                "n_results": n_results,
            }
            
            if where:
                data["where"] = where
            
            collection_name = collection or self.collection_name
            result = self._make_request(
                "POST",
                f"/api/v1/collections/{collection_name}/query",
                json_data=data,
            )
            
            # Parse results
            documents = []
            ids = result.get("ids", [[]])[0]
            contents = result.get("documents", [[]])[0]
            metadatas = result.get("metadatas", [[]])[0]
            distances = result.get("distances", [[]])[0]
            
            for i, doc_id in enumerate(ids):
                # Convert distance to similarity score (assuming L2 distance)
                # Lower distance = higher similarity
                distance = distances[i] if i < len(distances) else 0
                score = 1.0 / (1.0 + distance)  # Convert to 0-1 range
                
                documents.append(RAGDocument(
                    doc_id=doc_id,
                    content=contents[i] if i < len(contents) else "",
                    metadata=metadatas[i] if i < len(metadatas) else {},
                    score=score,
                ))
            
            return RAGSearchResult(
                success=True,
                documents=documents,
                total_count=len(documents),
                message="Search completed successfully",
            )
        except httpx.HTTPError as e:
            logger.error(f"Failed to search: {e}")
            return RAGSearchResult(
                success=False,
                message=str(e),
            )

    def search_by_metadata(
        self,
        where: dict[str, Any],
        n_results: int = 100,
        collection: Optional[str] = None,
    ) -> RAGSearchResult:
        """Search for documents by metadata filter only.
        
        Args:
            where: Metadata filter (ChromaDB where clause)
            n_results: Maximum number of results
            collection: Collection name (uses default if None)
            
        Returns:
            RAGSearchResult
        """
        try:
            collection_name = collection or self.collection_name
            result = self._make_request(
                "POST",
                f"/api/v1/collections/{collection_name}/get",
                json_data={
                    "where": where,
                    "limit": n_results,
                },
            )
            
            documents = []
            ids = result.get("ids", [])
            contents = result.get("documents", [])
            metadatas = result.get("metadatas", [])
            
            for i, doc_id in enumerate(ids):
                documents.append(RAGDocument(
                    doc_id=doc_id,
                    content=contents[i] if i < len(contents) else "",
                    metadata=metadatas[i] if i < len(metadatas) else {},
                    score=1.0,  # No semantic search, all matches are equal
                ))
            
            return RAGSearchResult(
                success=True,
                documents=documents,
                total_count=len(documents),
                message="Search completed successfully",
            )
        except httpx.HTTPError as e:
            logger.error(f"Failed to search by metadata: {e}")
            return RAGSearchResult(
                success=False,
                message=str(e),
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
        """Save a project configuration.
        
        Args:
            project_id: Project identifier
            name: Project display name
            description: Project description
            config_data: Full configuration data
            
        Returns:
            RAGOperationResult
        """
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

        # Use upsert to handle both new and existing projects
        return self.upsert_document(doc_id, content, metadata)

    def get_project_config(self, project_id: str) -> Optional[RAGDocument]:
        """Get a project configuration.
        
        Args:
            project_id: Project identifier
            
        Returns:
            RAGDocument if found, None otherwise
        """
        return self.get_document(f"project:{project_id}")

    def list_projects(self) -> list[RAGDocument]:
        """List all project configurations.
        
        Returns:
            List of project config documents
        """
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
        """Find projects similar to the given name/description.
        
        Args:
            name: Project name
            description: Project description
            threshold: Minimum similarity score (0.0-1.0)
            exclude_project_id: Project ID to exclude from results
            
        Returns:
            List of similar project documents
        """
        query = f"{name} {description}".strip()
        
        result = self.search(
            query=query,
            n_results=10,
            where={"type": {"$eq": "project_config"}},
        )
        
        if not result.success:
            return []
        
        # Filter by threshold and exclude self
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
        """Delete a project configuration.
        
        Args:
            project_id: Project identifier
            
        Returns:
            RAGOperationResult
        """
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
        """Add a knowledge entry.
        
        Args:
            content: Knowledge content
            category: Category (問題解決/技術Tips/etc.)
            tags: Search tags
            project: Related project (None for general knowledge)
            source: Information source
            
        Returns:
            RAGOperationResult
        """
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
        """Search for knowledge entries.

        Args:
            query: Search query
            category: Filter by category
            project: Filter by project (None includes general)
            tags: Filter by tags (AND condition)
            n_results: Maximum results

        Returns:
            RAGSearchResult
        """
        # Note: We don't filter by type="knowledge" because older data
        # added directly to RAG server may not have the type field.
        # Instead, we exclude project_config in post-filtering.
        where: dict[str, Any] = {}

        if category:
            where["category"] = {"$eq": category}

        if project:
            # Include both project-specific and general knowledge
            where["$or"] = [
                {"project": {"$eq": project}},
                {"project": {"$eq": ""}},
            ]

        # Note: Tag filtering with AND condition is complex in ChromaDB
        # We'll filter in Python after the search
        # Request more results to account for post-filtering
        needs_post_filter = tags is not None
        multiplier = 3 if needs_post_filter else 2  # Extra buffer for project_config exclusion

        result = self.search(
            query=query,
            n_results=n_results * multiplier,
            where=where if where else None,
        )

        if not result.success:
            return result

        # Post-filter: exclude project_config documents
        result.documents = [
            doc for doc in result.documents
            if doc.metadata.get("type") != "project_config"
        ]

        # Filter by tags if specified
        if tags:
            filtered = []
            for doc in result.documents:
                doc_tags = doc.metadata.get("tags", [])
                if all(tag in doc_tags for tag in tags):
                    filtered.append(doc)
                    if len(filtered) >= n_results:
                        break

            result.documents = filtered
        else:
            # Limit to n_results
            result.documents = result.documents[:n_results]

        result.total_count = len(result.documents)

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
        """Add a catalog entry.
        
        Args:
            doc_id: Document ID
            name: Document name
            doc_type: Document type (設計書/実装手順書/etc.)
            project: Project ID
            phase_task: Phase-Task identifier
            metadata: Additional metadata
            
        Returns:
            RAGOperationResult
        """
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
        """Search the catalog.
        
        Args:
            query: Search query
            project: Filter by project
            doc_type: Filter by document type
            phase_task: Filter by phase-task
            n_results: Maximum results
            
        Returns:
            RAGSearchResult
        """
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
        """Delete all catalog entries for a project.

        Args:
            project: Project ID

        Returns:
            Number of entries deleted
        """
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

    def get_catalog_entry(
        self,
        doc_id: str,
        project: str,
    ) -> Optional[RAGDocument]:
        """Get a catalog entry by document ID and project.

        Args:
            doc_id: Document ID
            project: Project ID

        Returns:
            RAGDocument if found, None otherwise
        """
        catalog_id = f"catalog:{project}:{doc_id}"
        return self.get_document(catalog_id)

    def delete_catalog_entry(
        self,
        doc_id: str,
        project: str,
    ) -> RAGOperationResult:
        """Delete a catalog entry by document ID and project.

        Args:
            doc_id: Document ID
            project: Project ID

        Returns:
            RAGOperationResult
        """
        catalog_id = f"catalog:{project}:{doc_id}"
        return self.delete_document(catalog_id)

    def delete_knowledge_by_doc_id(
        self,
        doc_id: str,
        project: Optional[str] = None,
    ) -> int:
        """Delete knowledge entries associated with a document ID.

        Args:
            doc_id: Document ID to find related knowledge
            project: Optional project filter

        Returns:
            Number of knowledge entries deleted
        """
        # Build where clause
        where: dict[str, Any] = {
            "type": {"$eq": "knowledge"},
            "doc_id": {"$eq": doc_id},
        }
        if project:
            where["project"] = {"$eq": project}

        result = self.search_by_metadata(
            where=where,
            n_results=1000,
        )

        count = 0
        for doc in result.documents:
            if self.delete_document(doc.doc_id).success:
                count += 1

        return count

    # ===========================
    # Document Type Operations
    # ===========================

    def _ensure_document_types_collection(self) -> bool:
        """Ensure the document types collection exists.

        Returns:
            True if collection exists or was created, False on error.
        """
        try:
            response = self._client.get(
                f"{self.base_url}/api/v1/collections/{DOCUMENT_TYPES_COLLECTION}",
            )
            if response.status_code == 200:
                return True
            elif response.status_code == 404:
                # Create the collection
                create_response = self._client.post(
                    f"{self.base_url}/api/v1/collections",
                    json={"name": DOCUMENT_TYPES_COLLECTION},
                )
                if create_response.status_code in (200, 201):
                    logger.info(f"Created collection '{DOCUMENT_TYPES_COLLECTION}'")
                    return True
                logger.warning(
                    f"Failed to create {DOCUMENT_TYPES_COLLECTION} collection: "
                    f"{create_response.status_code}"
                )
                return False
            return False
        except Exception as e:
            logger.warning(f"Could not verify/create document types collection: {e}")
            return False

    def save_document_type(
        self,
        type_id: str,
        name: str,
        description: str,
        folder_name: str,
    ) -> RAGOperationResult:
        """Save a document type to RAG for semantic search.

        The content is constructed from type_id, name, and description to enable
        semantic matching across languages (e.g., "api_spec" matches "API仕様").

        Args:
            type_id: Unique document type ID (e.g., "api_spec")
            name: Display name (e.g., "API仕様書")
            description: Description of the document type
            folder_name: Folder name in Google Drive

        Returns:
            RAGOperationResult
        """
        if not self._ensure_document_types_collection():
            return RAGOperationResult(
                success=False,
                doc_id=f"doctype:{type_id}",
                message="Document types collection not available",
            )

        doc_id = f"doctype:{type_id}"
        # Combine all searchable text for embedding
        content = f"{type_id} {name} {description}".strip()

        metadata = {
            "type_id": type_id,
            "name": name,
            "description": description,
            "folder_name": folder_name,
            "updated_at": datetime.now().isoformat(),
        }

        return self.upsert_document(
            doc_id=doc_id,
            content=content,
            metadata=metadata,
            collection=DOCUMENT_TYPES_COLLECTION,
        )

    def find_similar_document_types(
        self,
        query: str,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        limit: int = 5,
    ) -> list[RAGDocument]:
        """Find document types semantically similar to the query.

        Uses BGE-M3 embeddings for multilingual semantic matching.
        For example, "api仕様" can match "api_spec".

        Args:
            query: Search query (can be type_id, name, or description in any language)
            threshold: Minimum similarity score (0.0-1.0), default 0.75
            limit: Maximum number of results

        Returns:
            List of matching RAGDocument objects, sorted by similarity (highest first).
            Each document's metadata contains: type_id, name, description, folder_name.
        """
        if not self._available:
            logger.warning("RAG not available, cannot search document types")
            return []

        if not self._ensure_document_types_collection():
            return []

        result = self.search(
            query=query,
            n_results=limit,
            collection=DOCUMENT_TYPES_COLLECTION,
        )

        if not result.success:
            logger.warning(f"Document type search failed: {result.message}")
            return []

        # Filter by threshold
        matches = [doc for doc in result.documents if doc.score >= threshold]

        logger.debug(
            f"Document type search for '{query}': "
            f"{len(matches)} matches above threshold {threshold}"
        )

        return matches

    def delete_document_type_from_rag(self, type_id: str) -> RAGOperationResult:
        """Delete a document type from RAG.

        Args:
            type_id: Document type ID to delete

        Returns:
            RAGOperationResult
        """
        doc_id = f"doctype:{type_id}"
        return self.delete_document(doc_id, collection=DOCUMENT_TYPES_COLLECTION)

    def sync_document_types(
        self,
        types: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Sync document types from JSON storage to RAG.

        This is typically called on startup to ensure RAG has all registered types.

        Args:
            types: List of document type dicts with keys:
                   type_id, name, description, folder_name

        Returns:
            Dict with sync statistics:
            - synced: Number successfully synced
            - failed: Number that failed
            - errors: List of error messages
        """
        if not self._available:
            return {
                "synced": 0,
                "failed": len(types),
                "errors": ["RAG server not available"],
            }

        if not self._ensure_document_types_collection():
            return {
                "synced": 0,
                "failed": len(types),
                "errors": ["Could not create document types collection"],
            }

        synced = 0
        failed = 0
        errors = []

        for type_data in types:
            type_id = type_data.get("type_id", "")
            if not type_id:
                errors.append("Missing type_id in document type data")
                failed += 1
                continue

            result = self.save_document_type(
                type_id=type_id,
                name=type_data.get("name", type_id),
                description=type_data.get("description", ""),
                folder_name=type_data.get("folder_name", ""),
            )

            if result.success:
                synced += 1
            else:
                failed += 1
                errors.append(f"{type_id}: {result.message}")

        logger.info(f"Synced document types to RAG: {synced} succeeded, {failed} failed")

        return {
            "synced": synced,
            "failed": failed,
            "errors": errors,
        }
