"""Filesystem implementation of :class:`DocumentStore`.

Documents are Markdown files with YAML frontmatter, and they live in one of
two tiers (design §6.3.1):

**canonical** -- ``<root>/<repo>/<docs_dir>/<folder_path>/<slug>.md``.
``<root>`` is ``/srv/docs`` on sg-ai-server-01, holding one Git clone per
repository listed in ``repos.toml``. A systemd timer advances those clones
with ``git pull --ff-only``, so nothing writes into them: a dirty tree
stalls the sync.

**working** -- ``<work_root>/<repo>/<docs_dir>/<folder_path>/<slug>.md``.
``<work_root>`` is ``/srv/docs-work``, outside Git, holding documents that
are still being written. Every write lands here. Promotion to canonical is
an explicit pull request, once the document is settled.

The layout mirrors canonical so promotion is a straight copy, including
which ``docs_dir`` a document belongs in -- Spirrow-VoxelWorld has two.

Callers do not see the distinction. ``read`` and ``scan`` cover both tiers;
``get_document(doc_id)`` never reveals which one answered. That is what
makes two tiers viable at all, and it is why writes do not have to become
pull requests -- see §9.14 for why that earlier design was retracted.

A document in both tiers is reconciled by :meth:`reconcile`, which the sync
job runs after pulling. Reconciliation is at sync time rather than at merge
time on purpose: deleting the working copy the moment a pull request merges
would leave the document invisible until the next pull.

Repository map (``/srv/docs/repos.toml``)::

    [repos]
    spirrow-docs       = "spirrow-docs"
    spirrow-voxelworld = "Spirrow-VoxelWorld"

    [docs_dirs]
    spirrow-voxelworld = ["Docs", "docs"]

The ``[repos]`` key is the repository identifier a project points at (its
``root_folder_id``, reused as a repo id in filesystem mode -- design §6.2);
the value is the clone's directory name under ``<root>``. Keep the key equal
to the Magickit project id: the working tier is named by it.

``[docs_dirs]`` is optional and names the directories inside a clone that
hold documents. It defaults to ``["docs"]``. Spirrow-VoxelWorld needs it:
that repository keeps its specs in ``Docs/`` and only ``branching.md`` in
``docs/``, both are live, and ``/srv/docs`` sits on a case-sensitive
filesystem -- so a single lowercase guess finds one file out of thirteen.
The first entry is where new documents are written.
"""

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Optional

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
from .infra_registry import Finding, Registry, load_registry, registry_path_for

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..tools.project_tools import ProjectTools

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
MARKDOWN_MIME = "text/markdown"

WORKING = "working"
CANONICAL = "canonical"

# The registry's own repository. It is the one place real infra values belong,
# so it is neither substituted on write nor reported by the §3.1 check.
DOCS_REPO = "spirrow-docs"


@dataclass
class ReconcileEntry:
    """One working-tier document, as :meth:`reconcile` found it.

    ``state`` is one of:

    - ``"promoted"`` -- the same id is in canonical with the same body. The
      working copy was removed (unless ``remove_promoted=False``).
    - ``"diverged"`` -- the id is in canonical but the bodies differ. The
      working copy is kept: someone edited it after opening the pull
      request, and deleting it would lose that edit.
    - ``"draft"`` -- not in canonical yet. ``stale`` says whether it has sat
      here longer than the threshold.
    """

    doc_id: str
    state: str
    working_path: str
    canonical_path: Optional[str] = None
    age_days: float = 0.0
    stale: bool = False


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
    """Documents as Markdown files, across a working and a canonical tier."""

    def __init__(
        self,
        root: str = "/srv/docs",
        repos_config: Optional[str] = None,
        project_tools: Optional["ProjectTools"] = None,
        user_name: str = "default",
        work_root: str = "/srv/docs-work",
        stale_after_days: float = 14.0,
        infra_registry: Optional[str] = None,
    ):
        """Initialize the filesystem store.

        Args:
            root: Directory holding one Git clone per repository. Read-only:
                the sync timer owns it.
            repos_config: Path to ``repos.toml``. Defaults to
                ``<root>/repos.toml``.
            project_tools: Used to map a project to its repository. Without
                it, a project id is taken to be a repository id directly.
            user_name: Default user ID for project config lookups.
            work_root: Directory holding the working tier, outside Git.
            stale_after_days: How long a draft may sit in the working tier
                before :meth:`reconcile` flags it.
            infra_registry: Path to the infra placeholder registry. Defaults to
                ``<root>/spirrow-docs/docs/platform/infra-registry.md``.
        """
        self.root = Path(root)
        self.work_root = Path(work_root)
        self.repos_config = (
            Path(repos_config) if repos_config else self.root / "repos.toml"
        )
        self.project_tools = project_tools
        self.user_name = user_name
        self.stale_after_days = stale_after_days
        self._repos: Optional[dict[str, str]] = None
        self._docs_dirs: dict[str, list[str]] = {}
        # mtime of repos.toml when it was last read, so a repository added
        # to the file is picked up without restarting the server.
        self._repos_mtime: Optional[float] = None
        # doc_id -> path, rebuilt by _index() on demand.
        self._index_cache: Optional[dict[str, Path]] = None
        # Infra placeholders (conventions §3.1). Re-read when the file moves,
        # like repos.toml: the sync timer can update it under a running server.
        self.infra_registry_path = registry_path_for(self.root, infra_registry)
        self._registry: Optional[Registry] = None
        self._registry_mtime: Optional[float] = None

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

    @property
    def registry(self) -> Registry:
        """The infra placeholder table, re-read when the file changes."""
        try:
            mtime: Optional[float] = self.infra_registry_path.stat().st_mtime
        except OSError:
            mtime = None
        if self._registry is None or mtime != self._registry_mtime:
            self._registry = load_registry(self.infra_registry_path)
            self._registry_mtime = mtime
        return self._registry

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

    def _repo_dir(self, repo: str, tier: str = CANONICAL) -> Path:
        if tier == WORKING:
            # The working tier is named by the repo id, not the clone's
            # directory name, so it does not inherit GitHub's casing.
            return self.work_root / repo
        return self.root / self.repos.get(repo, repo)

    def _docs_dir(self, repo: str, tier: str = CANONICAL) -> Path:
        """Where new documents go: the first configured directory."""
        return self._repo_dir(repo, tier) / self.docs_dirs(repo)[0]

    def _docs_dir_paths(self, repo: str, tier: str = CANONICAL) -> list[Path]:
        """Every configured document directory, in order."""
        repo_dir = self._repo_dir(repo, tier)
        return [repo_dir / name for name in self.docs_dirs(repo)]

    def _docs_dir_of(self, repo: str, path: Path) -> Path:
        """Which configured directory a path lives under, in either tier.

        Falls back to the canonical primary so a caller always gets a
        usable base for relative-path work.
        """
        for tier in (CANONICAL, WORKING):
            for candidate in self._docs_dir_paths(repo, tier):
                try:
                    path.relative_to(candidate)
                except ValueError:
                    continue
                return candidate
        return self._docs_dir(repo)

    def _tier_of(self, path: Path) -> str:
        try:
            path.relative_to(self.work_root)
        except ValueError:
            return CANONICAL
        return WORKING

    def _working_twin(self, repo: str, canonical_path: Path) -> Path:
        """Where ``canonical_path`` would live in the working tier.

        The two layouts mirror each other, so this preserves both the
        ``docs_dir`` a document belongs in and its folder path -- promotion
        is then a straight copy back.
        """
        base = self._docs_dir_of(repo, canonical_path)
        relative = canonical_path.relative_to(base)
        return self._repo_dir(repo, WORKING) / base.name / relative

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
        """Build (or reuse) the ``doc_id -> path`` map across both tiers.

        The working tier is indexed last and wins: if a document is in both,
        the working copy is the more recent edit. A pair that should not
        persist is what :meth:`reconcile` resolves.
        """
        if self._index_cache is not None and not refresh:
            return self._index_cache

        index: dict[str, Path] = {}
        for tier in (CANONICAL, WORKING):
            for repo in self.repos:
                for path, frontmatter, _ in self._walk(repo, tier):
                    doc_id = self._doc_id_for(repo, path, frontmatter)
                    previous = index.get(doc_id)
                    if (
                        previous is not None
                        and previous != path
                        and self._tier_of(previous) == tier
                    ):
                        logger.warning(
                            f"Duplicate doc_id '{doc_id}' within {tier}: "
                            f"{previous} and {path}. Keeping the first."
                        )
                        continue
                    index[doc_id] = path

        self._index_cache = index
        return index

    def _walk(
        self, repo: str, tier: str = CANONICAL
    ) -> Iterator[tuple[Path, dict, str]]:
        """Yield ``(path, frontmatter, body)`` for each Markdown file."""
        seen: set[Path] = set()
        for docs_dir in self._docs_dir_paths(repo, tier):
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
        """Locate a document, rebuilding the index when the cache is stale.

        Both misses have to trigger a rebuild, not just the obvious one:

        - the id is absent, because the document was created since the walk;
        - the id is present but the file is gone, because something outside
          this process moved or removed it.

        The second is the normal path, not an edge case. ``reconcile`` runs
        in the sync job -- a separate process -- and removes the working
        copy of every document whose pull request has merged, so this
        process's cache still points at a file that no longer exists. Only
        refreshing on ``path is None`` left those documents unreadable until
        a restart while ``search_catalog`` went on listing them: findable
        but unopenable, and no way back.
        """
        index = self._index()
        path = index.get(doc_id)
        if path is None or not path.exists():
            index = self._index(refresh=True)
            path = index.get(doc_id)
        if path is None or not path.exists():
            raise DocumentNotFound(doc_id)
        return path

    def _repo_of_path(self, path: Path) -> str:
        for tier in (CANONICAL, WORKING):
            for repo in self.repos:
                try:
                    path.relative_to(self._repo_dir(repo, tier))
                except ValueError:
                    continue
                return repo
        raise DocumentStoreError(f"Path '{path}' is not inside any known repo")

    def _to_stored(self, repo: str, path: Path, *, resolve: bool = False) -> StoredDoc:
        """Read one file into a StoredDoc.

        ``resolve`` fills infra placeholders in with their real values. It is
        off for scanning and indexing on purpose: the catalog and the §3.1
        check both have to see what is actually committed, and a resolved scan
        would put real host names into the vector index and make every correct
        placeholder look like a violation.
        """
        text = path.read_text(encoding="utf-8")
        if resolve:
            text = self.registry.resolve(text)
        frontmatter, body = parse_frontmatter(text)
        doc_id = self._doc_id_for(repo, path, frontmatter)
        title = str(frontmatter.get("title") or path.stem)
        root = self.work_root if self._tier_of(path) == WORKING else self.root
        try:
            relative = path.relative_to(root).as_posix()
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

    def _for_disk(self, repo: str, body: str) -> str:
        """Take real infra values back out before a document is written.

        Conventions §3.1: the values live in one registry and every other
        repository carries placeholders. Doing it here means a caller can write
        the host name it just read and still not put it in a file.

        ``spirrow-docs`` is the registry's own home and keeps real values.
        """
        if repo == DOCS_REPO:
            return body
        return self.registry.substitute(body)

    def check_placeholders(
        self, project_id: Optional[str] = None
    ) -> list[Finding]:
        """Real infra values sitting where a placeholder belongs (§3.1).

        This is the continuous half of the guard: it sees every clone the sync
        timer maintains, including documents committed straight to git without
        passing through this store. It reports after the fact -- the pre-commit
        hook in spirrow-docs is what stops a value before it is pushed.
        """
        registry = self.registry
        if registry.empty:
            raise DocumentStoreError(
                f"infra registry unusable at {self.infra_registry_path}; "
                "refusing to report a clean check"
            )
        findings: list[Finding] = []
        for repo in self._iter_repos(project_id):
            if repo == DOCS_REPO:
                continue
            for tier in (CANONICAL, WORKING):
                for path, _, _ in self._walk(repo, tier):
                    try:
                        text = path.read_text(encoding="utf-8")
                    except OSError:
                        continue
                    findings.extend(registry.findings(text, str(path)))
        return findings

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
        repo = self._repo_for_project(project_id)

        target_dir = self._docs_dir(repo, WORKING)
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
            relative = path.relative_to(self._docs_dir(repo, WORKING))
            frontmatter["id"] = (
                f"{product}:{'/'.join(relative.with_suffix('').parts)}"
            )

        path.write_text(
            render_frontmatter(frontmatter, self._for_disk(repo, content)),
            encoding="utf-8",
        )
        self._index_cache = None

        return self._to_stored(repo, path, resolve=True)

    def read(self, doc_id: str) -> StoredDoc:
        path = self._resolve_path(doc_id)
        return self._to_stored(self._repo_of_path(path), path, resolve=True)

    def write(self, doc_id: str, content: str, *, append: bool = False) -> None:
        """Write to the working tier, copying from canonical if needed.

        Editing a published document copies it into the working tier first
        and applies the edit there, so the canonical clone stays clean and
        the change can be reviewed as a pull request later.
        """
        path = self._resolve_path(doc_id)
        repo = self._repo_of_path(path)

        frontmatter, body = parse_frontmatter(
            path.read_text(encoding="utf-8")
        )
        if self._tier_of(path) == CANONICAL:
            path = self._working_twin(repo, path)
            path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(
                f"'{doc_id}' is canonical; editing a working copy at {path}"
            )
            self._index_cache = None

        new_body = (body + content) if append else content
        path.write_text(
            render_frontmatter(frontmatter, self._for_disk(repo, new_body)),
            encoding="utf-8",
        )

    def move(self, doc_id: str, *, project_id: str, folder_path: str) -> str:
        path = self._resolve_path(doc_id)
        if self._tier_of(path) == CANONICAL:
            raise DocumentStoreError(
                f"'{doc_id}' is canonical; moving it is a rename in Git and "
                "has to go through a pull request, not this store."
            )

        repo = self._repo_for_project(project_id)
        target_dir = self._docs_dir(repo, WORKING)
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
        # The id lives in frontmatter, so it survives the move.
        return doc_id

    def delete(self, doc_id: str, *, permanent: bool = False) -> None:
        """Archive by default (design §6.3), unlink only when asked."""
        path = self._resolve_path(doc_id)
        if self._tier_of(path) == CANONICAL:
            raise DocumentStoreError(
                f"'{doc_id}' is canonical; deleting it has to go through a "
                "pull request, not this store."
            )

        if permanent:
            path.unlink()
            self._index_cache = None
            return

        frontmatter, body = parse_frontmatter(
            path.read_text(encoding="utf-8")
        )
        frontmatter["status"] = "archived"
        path.write_text(
            render_frontmatter(frontmatter, body), encoding="utf-8"
        )

    def scan(self, project_id: Optional[str] = None) -> list[StoredDoc]:
        """Every document in both tiers, working shadowing canonical."""
        by_id: dict[str, StoredDoc] = {}
        for tier in (CANONICAL, WORKING):
            for repo in self._iter_repos(project_id):
                for path, _, _ in self._walk(repo, tier):
                    doc = self._to_stored(repo, path)
                    by_id[doc.doc_id] = doc
        return list(by_id.values())

    def ensure_folder(self, *, project_id: str, folder_path: str) -> bool:
        repo = self._repo_for_project(project_id)
        target = self._docs_dir(repo, WORKING)
        if folder_path:
            target = target / Path(folder_path.strip("/"))
        if target.exists():
            return False
        target.mkdir(parents=True, exist_ok=True)
        return True

    # ------------------------------------------------------------------
    # Reconciliation (design §6.4.1)
    # ------------------------------------------------------------------

    def reconcile(
        self,
        project_id: Optional[str] = None,
        *,
        remove_promoted: bool = True,
    ) -> list[ReconcileEntry]:
        """Compare the working tier against canonical after a sync.

        Run by the sync job once the clones have been pulled, not when a
        pull request merges: between a merge and the next five-minute pull
        the canonical copy does not exist yet, so removing the working copy
        at merge time would leave the document invisible.

        A working copy whose body differs from canonical is kept and
        reported, never removed -- that is someone's edit made after the
        pull request went out.

        Args:
            project_id: Restrict to one project; ``None`` means all.
            remove_promoted: Delete working copies that match canonical.
                ``False`` reports without touching anything.
        """
        canonical: dict[str, Path] = {}
        for repo in self._iter_repos(project_id):
            for path, frontmatter, _ in self._walk(repo, CANONICAL):
                canonical.setdefault(
                    self._doc_id_for(repo, path, frontmatter), path
                )

        now = time.time()
        entries: list[ReconcileEntry] = []
        removed = False

        for repo in self._iter_repos(project_id):
            for path, frontmatter, body in self._walk(repo, WORKING):
                doc_id = self._doc_id_for(repo, path, frontmatter)
                try:
                    age_days = (now - path.stat().st_mtime) / 86400.0
                except OSError:
                    age_days = 0.0

                twin = canonical.get(doc_id)
                if twin is None:
                    entries.append(ReconcileEntry(
                        doc_id=doc_id,
                        state="draft",
                        working_path=path.as_posix(),
                        age_days=age_days,
                        stale=age_days >= self.stale_after_days,
                    ))
                    continue

                _, twin_body = parse_frontmatter(
                    twin.read_text(encoding="utf-8")
                )
                if twin_body == body:
                    if remove_promoted:
                        path.unlink()
                        removed = True
                        logger.info(
                            f"'{doc_id}' promoted; removed working copy {path}"
                        )
                    entries.append(ReconcileEntry(
                        doc_id=doc_id,
                        state="promoted",
                        working_path=path.as_posix(),
                        canonical_path=twin.as_posix(),
                        age_days=age_days,
                    ))
                else:
                    logger.warning(
                        f"'{doc_id}' differs between the working copy "
                        f"({path}) and canonical ({twin}). Keeping the "
                        "working copy; it holds an edit made after the pull "
                        "request."
                    )
                    entries.append(ReconcileEntry(
                        doc_id=doc_id,
                        state="diverged",
                        working_path=path.as_posix(),
                        canonical_path=twin.as_posix(),
                        age_days=age_days,
                        stale=age_days >= self.stale_after_days,
                    ))

        if removed:
            self._index_cache = None

        for entry in entries:
            if entry.stale and entry.state == "draft":
                logger.warning(
                    f"'{entry.doc_id}' has been in the working tier for "
                    f"{entry.age_days:.0f} days without reaching canonical."
                )

        return entries
