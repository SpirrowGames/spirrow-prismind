"""Filesystem implementation of :class:`DocumentStore`.

Documents are Markdown files with YAML frontmatter, laid out as::

    <root>/<repo>/docs/<folder_path>/<slug>.md

``<root>`` is ``/srv/docs`` on sg-ai-server-01, holding one Git clone per
repository listed in ``repos.toml``. A systemd timer keeps those clones
current with ``git pull --ff-only``; this store is the read side of that
arrangement, and :class:`DocumentPublisher` is the write side.

Repository map (``/srv/docs/repos.toml``)::

    [repos]
    spirrow-docs       = "spirrow-docs"
    spirrow-voxelworld = "Spirrow-VoxelWorld"

    [docs_dirs]
    spirrow-voxelworld = ["Docs", "docs"]

The ``[repos]`` key is the repository identifier a project points at (its
``root_folder_id``, reused as a repo id in filesystem mode -- design §6.2);
the value is the clone's directory name under ``<root>``.

``[docs_dirs]`` is optional and names the directories inside a clone that
hold documents. It defaults to ``["docs"]``. Spirrow-VoxelWorld needs it:
that repository keeps its specs in ``Docs/`` and only ``branching.md`` in
``docs/``, both are live, and ``/srv/docs`` sits on a case-sensitive
filesystem -- so a single lowercase guess finds one file out of thirteen.
The first entry is where new documents are written.
"""

import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Sequence

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

import yaml

from .document_store import (
    DocumentNotFound,
    DocumentStore,
    DocumentStoreError,
    StoredDoc,
    slugify,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..tools.project_tools import ProjectTools

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
MARKDOWN_MIME = "text/markdown"


class DocumentPublisher(ABC):
    """Gets filesystem writes back into Git.

    Writing straight into a clone that a timer advances with
    ``git pull --ff-only`` would leave that clone dirty and stall the sync,
    so a store with no publisher refuses to write at all rather than
    corrupt the sync loop.

    Design §6.3 fixes the contract: a write becomes a working branch plus a
    pull request; it is never committed to the clone's checked-out branch
    and never auto-merged.
    """

    @abstractmethod
    def publish(
        self, repo: str, paths: Sequence[Path], message: str
    ) -> Optional[str]:
        """Publish changed paths for one repository.

        Returns:
            A pull request URL, or None if the publisher batches instead of
            opening one per call.
        """
        ...


class NullPublisher(DocumentPublisher):
    """Leaves writes in the working tree and says so.

    Only for a scratch ``root`` that is not a synced clone -- tests, or a
    local experiment. Configure it deliberately; it is not the default.
    """

    def publish(
        self, repo: str, paths: Sequence[Path], message: str
    ) -> Optional[str]:
        logger.warning(
            f"NullPublisher: {len(paths)} path(s) in '{repo}' left uncommitted "
            f"({message}). Nothing will reach Git."
        )
        return None


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown document into (frontmatter, body).

    A document with no frontmatter block, or with one that is not a YAML
    mapping, yields an empty dict and the original text unchanged.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        logger.warning(f"Malformed frontmatter, ignoring it: {e}")
        return {}, text

    if not isinstance(loaded, dict):
        return {}, text

    return loaded, text[match.end():]


def render_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    """Inverse of :func:`parse_frontmatter`."""
    if not frontmatter:
        return body
    dumped = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    return f"---\n{dumped}---\n{body}"


class FilesystemDocumentStore(DocumentStore):
    """Documents stored as Markdown files in Git-synced clones."""

    def __init__(
        self,
        root: str = "/srv/docs",
        repos_config: Optional[str] = None,
        project_tools: Optional["ProjectTools"] = None,
        publisher: Optional[DocumentPublisher] = None,
        user_name: str = "default",
    ):
        """Initialize the filesystem store.

        Args:
            root: Directory holding one clone per repository.
            repos_config: Path to ``repos.toml``. Defaults to
                ``<root>/repos.toml``.
            project_tools: Used to map a project to its repository. Without
                it, a project id is taken to be a repository id directly.
            publisher: How writes reach Git. ``None`` makes the store
                read-only.
            user_name: Default user ID for project config lookups.
        """
        self.root = Path(root)
        self.repos_config = (
            Path(repos_config) if repos_config else self.root / "repos.toml"
        )
        self.project_tools = project_tools
        self.publisher = publisher
        self.user_name = user_name
        self._repos: Optional[dict[str, str]] = None
        self._docs_dirs: dict[str, list[str]] = {}
        # mtime of repos.toml when it was last read, so a repository added
        # to the file is picked up without restarting the server.
        self._repos_mtime: Optional[float] = None
        # doc_id -> path, rebuilt by _index() on demand.
        self._index_cache: Optional[dict[str, Path]] = None

    # ------------------------------------------------------------------
    # Repository / path resolution
    # ------------------------------------------------------------------

    @property
    def repos(self) -> dict[str, str]:
        """Repository id -> directory name, from ``repos.toml``.

        Re-read when the file's mtime moves. Without this, adding a
        repository to ``repos.toml`` needs a Prismind restart before the
        sync timer can see it -- which is not obvious from the outside and
        cost a confused half hour during the first deployment.
        """
        mtime = self._repos_config_mtime()
        if self._repos is None or mtime != self._repos_mtime:
            self._repos = self._load_repos()
            self._repos_mtime = mtime
            self._index_cache = None
        return self._repos

    def _repos_config_mtime(self) -> Optional[float]:
        try:
            return self.repos_config.stat().st_mtime
        except OSError:
            return None

    def docs_dirs(self, repo: str) -> list[str]:
        """Document directory names inside ``repo``'s clone."""
        self.repos  # ensure repos.toml has been read
        return self._docs_dirs.get(repo) or ["docs"]

    def _load_repos(self) -> dict[str, str]:
        if not self.repos_config.exists():
            logger.warning(
                f"repos config not found at {self.repos_config}; "
                "falling back to directory names under root"
            )
            if not self.root.exists():
                return {}
            return {
                p.name: p.name for p in sorted(self.root.iterdir()) if p.is_dir()
            }

        with open(self.repos_config, "rb") as f:
            data = tomllib.load(f)

        docs_dirs: dict[str, list[str]] = {}
        for key, value in (data.get("docs_dirs") or {}).items():
            if isinstance(value, str):
                value = [value]
            names = [str(v).strip("/") for v in value if str(v).strip("/")]
            if names:
                docs_dirs[str(key)] = names
        self._docs_dirs = docs_dirs

        repos = data.get("repos", {})
        return {str(k): str(v) for k, v in repos.items()}

    def _repo_for_project(self, project_id: str) -> str:
        """Map a project to its repository id.

        Design §6.2: in filesystem mode a project's ``root_folder_id``
        carries a repository identifier instead of a Drive folder id. A
        project id that is itself a known repository also resolves, which
        is the common case.
        """
        if self.project_tools is not None:
            config = self.project_tools.get_project_config(
                project=project_id, user=self.user_name
            )
            candidate = getattr(config, "root_folder_id", "") if config else ""
            if candidate and candidate in self.repos:
                return candidate

        if project_id in self.repos:
            return project_id

        raise DocumentStoreError(
            f"Project '{project_id}' does not map to any repository in "
            f"{self.repos_config}. Set the project's root_folder_id to a "
            f"repository id, or add the repository to repos.toml."
        )

    def _repo_dir(self, repo: str) -> Path:
        directory = self.repos.get(repo, repo)
        return self.root / directory

    def _docs_dir(self, repo: str) -> Path:
        """Where new documents are written: the first configured directory."""
        return self._repo_dir(repo) / self.docs_dirs(repo)[0]

    def _docs_dir_paths(self, repo: str) -> list[Path]:
        """Every configured document directory, in order."""
        repo_dir = self._repo_dir(repo)
        return [repo_dir / name for name in self.docs_dirs(repo)]

    def _docs_dir_of(self, repo: str, path: Path) -> Path:
        """Which configured directory a path lives under.

        Falls back to the primary one so a caller always gets a usable base
        for relative-path work.
        """
        for candidate in self._docs_dir_paths(repo):
            try:
                path.relative_to(candidate)
            except ValueError:
                continue
            return candidate
        return self._docs_dir(repo)

    def _require_writable(self) -> DocumentPublisher:
        if self.publisher is None:
            raise DocumentStoreError(
                "This FilesystemDocumentStore is read-only: no publisher is "
                "configured. Writing into a clone that the sync timer "
                "advances with `git pull --ff-only` would stall the sync, so "
                "writes require a DocumentPublisher (design §6.3)."
            )
        return self.publisher

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def _doc_id_for(self, repo: str, path: Path, frontmatter: dict) -> str:
        """Frontmatter ``id`` if present, else a provisional id.

        The provisional form is ``<product>:<relative slug path>``; design
        §6.3 requires a warning so the missing ``id`` gets fixed rather
        than quietly becoming load-bearing.
        """
        explicit = frontmatter.get("id")
        if explicit:
            return str(explicit)

        product = str(frontmatter.get("product") or repo)
        try:
            relative = path.relative_to(self._docs_dir_of(repo, path))
        except ValueError:
            relative = Path(path.name)
        slug = "/".join(relative.with_suffix("").parts)
        provisional = f"{product}:{slug}"
        logger.warning(
            f"'{path}' has no frontmatter 'id'; using provisional id "
            f"'{provisional}'. Add an 'id' to make it stable."
        )
        return provisional

    def _iter_repos(self, project_id: Optional[str]) -> list[str]:
        if project_id is None:
            return list(self.repos.keys())
        return [self._repo_for_project(project_id)]

    def _index(self, refresh: bool = False) -> dict[str, Path]:
        """Build (or reuse) the ``doc_id -> path`` map across all repos."""
        if self._index_cache is not None and not refresh:
            return self._index_cache

        index: dict[str, Path] = {}
        for repo in self.repos:
            for path, frontmatter, _ in self._walk(repo):
                doc_id = self._doc_id_for(repo, path, frontmatter)
                if doc_id in index and index[doc_id] != path:
                    logger.warning(
                        f"Duplicate doc_id '{doc_id}': {index[doc_id]} and "
                        f"{path}. Keeping the first."
                    )
                    continue
                index[doc_id] = path

        self._index_cache = index
        return index

    def _walk(self, repo: str):
        """Yield ``(path, frontmatter, body)`` for each Markdown file."""
        seen: set[Path] = set()
        for docs_dir in self._docs_dir_paths(repo):
            if not docs_dir.exists():
                continue
            for path in sorted(docs_dir.rglob("*.md")):
                if not path.is_file() or path in seen:
                    continue
                seen.add(path)
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError as e:
                    logger.warning(f"Could not read '{path}': {e}")
                    continue
                frontmatter, body = parse_frontmatter(text)
                yield path, frontmatter, body

    def _resolve_path(self, doc_id: str) -> Path:
        index = self._index()
        path = index.get(doc_id)
        if path is None:
            # A document created since the last walk is not in the cache.
            index = self._index(refresh=True)
            path = index.get(doc_id)
        if path is None or not path.exists():
            raise DocumentNotFound(doc_id)
        return path

    def _repo_of_path(self, path: Path) -> str:
        for repo in self.repos:
            repo_dir = self._repo_dir(repo)
            try:
                path.relative_to(repo_dir)
            except ValueError:
                continue
            return repo
        raise DocumentStoreError(f"Path '{path}' is not inside any known repo")

    def _to_stored(self, repo: str, path: Path) -> StoredDoc:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        doc_id = self._doc_id_for(repo, path, frontmatter)
        title = str(frontmatter.get("title") or path.stem)
        try:
            relative = path.relative_to(self.root).as_posix()
        except ValueError:
            relative = path.as_posix()
        return StoredDoc(
            doc_id=doc_id,
            title=title,
            body=body,
            url=f"file://{path.as_posix()}",
            mime_type=MARKDOWN_MIME,
            path=relative,
            frontmatter=frontmatter,
        )

    # ------------------------------------------------------------------
    # DocumentStore
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        project_id: str,
        folder_path: str,
        name: str,
        content: str,
        frontmatter: Optional[dict[str, Any]] = None,
    ) -> StoredDoc:
        publisher = self._require_writable()
        repo = self._repo_for_project(project_id)

        target_dir = self._docs_dir(repo)
        if folder_path:
            target_dir = target_dir / Path(folder_path.strip("/"))
        target_dir.mkdir(parents=True, exist_ok=True)

        path = target_dir / f"{slugify(name)}.md"
        if path.exists():
            raise DocumentStoreError(f"Document already exists: {path}")

        frontmatter = dict(frontmatter or {})
        frontmatter.setdefault("title", name)
        if "id" not in frontmatter:
            product = str(frontmatter.get("product") or repo)
            relative = path.relative_to(self._docs_dir_of(repo, path))
            frontmatter["id"] = (
                f"{product}:{'/'.join(relative.with_suffix('').parts)}"
            )

        path.write_text(
            render_frontmatter(frontmatter, content), encoding="utf-8"
        )
        self._index_cache = None
        publisher.publish(repo, [path], f"docs: add {name}")

        return self._to_stored(repo, path)

    def read(self, doc_id: str) -> StoredDoc:
        path = self._resolve_path(doc_id)
        return self._to_stored(self._repo_of_path(path), path)

    def write(self, doc_id: str, content: str, *, append: bool = False) -> None:
        publisher = self._require_writable()
        path = self._resolve_path(doc_id)
        repo = self._repo_of_path(path)

        frontmatter, body = parse_frontmatter(
            path.read_text(encoding="utf-8")
        )
        new_body = (body + content) if append else content
        path.write_text(
            render_frontmatter(frontmatter, new_body), encoding="utf-8"
        )
        publisher.publish(repo, [path], f"docs: update {doc_id}")

    def move(self, doc_id: str, *, project_id: str, folder_path: str) -> str:
        publisher = self._require_writable()
        path = self._resolve_path(doc_id)
        repo = self._repo_for_project(project_id)

        target_dir = self._docs_dir(repo)
        if folder_path:
            target_dir = target_dir / Path(folder_path.strip("/"))
        target_dir.mkdir(parents=True, exist_ok=True)

        destination = target_dir / path.name
        if destination == path:
            return doc_id
        if destination.exists():
            raise DocumentStoreError(
                f"Cannot move '{doc_id}': '{destination}' already exists"
            )

        path.rename(destination)
        self._index_cache = None
        publisher.publish(
            repo, [path, destination], f"docs: move {doc_id} to {folder_path}"
        )
        # The id lives in frontmatter, so it survives the move.
        return doc_id

    def delete(self, doc_id: str, *, permanent: bool = False) -> None:
        """Archive by default (design §6.3), unlink only when asked."""
        publisher = self._require_writable()
        path = self._resolve_path(doc_id)
        repo = self._repo_of_path(path)

        if permanent:
            path.unlink()
            self._index_cache = None
            publisher.publish(repo, [path], f"docs: remove {doc_id}")
            return

        frontmatter, body = parse_frontmatter(
            path.read_text(encoding="utf-8")
        )
        frontmatter["status"] = "archived"
        path.write_text(
            render_frontmatter(frontmatter, body), encoding="utf-8"
        )
        publisher.publish(repo, [path], f"docs: archive {doc_id}")

    def scan(self, project_id: Optional[str] = None) -> list[StoredDoc]:
        docs: list[StoredDoc] = []
        for repo in self._iter_repos(project_id):
            for path, _, _ in self._walk(repo):
                docs.append(self._to_stored(repo, path))
        return docs

    def ensure_folder(self, *, project_id: str, folder_path: str) -> bool:
        repo = self._repo_for_project(project_id)
        target = self._docs_dir(repo)
        if folder_path:
            target = target / Path(folder_path.strip("/"))
        if target.exists():
            return False
        target.mkdir(parents=True, exist_ok=True)
        return True
