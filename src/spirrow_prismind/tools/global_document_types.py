"""Global document type storage.

Manages document types that are shared across all projects.
Storage location: ~/.prismind_global_doc_types.json
"""

import json
import logging
from pathlib import Path
from typing import Optional

from ..models.document import DocumentType

logger = logging.getLogger(__name__)

# Default storage path
DEFAULT_STORAGE_PATH = Path.home() / ".prismind_global_doc_types.json"


class GlobalDocumentTypeStorage:
    """Global document type storage.

    Stores document types that are shared across all projects in a JSON file.
    """

    _instance: Optional["GlobalDocumentTypeStorage"] = None
    _storage_path: Path
    _types: dict[str, DocumentType]

    def __new__(cls, storage_path: Optional[Path] = None) -> "GlobalDocumentTypeStorage":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._storage_path = storage_path or DEFAULT_STORAGE_PATH
            cls._instance._types = {}
            cls._instance._load()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None

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

        logger.info(f"Deleted global document type: {type_id}")
        return True

    def reload(self) -> None:
        """Reload types from storage file."""
        self._load()
