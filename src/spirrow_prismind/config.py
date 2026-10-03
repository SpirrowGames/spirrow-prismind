"""Configuration management for Spirrow-Prismind."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

try:
    import tomllib
except ImportError:
    import tomli as tomllib


logger = logging.getLogger(__name__)


@dataclass
class GoogleConfig:
    """Google API configuration."""
    credentials_path: str = "credentials.json"
    token_path: str = "token.json"
    projects_folder_id: str = ""  # Root folder for all projects


@dataclass
class ServicesConfig:
    """External services configuration."""
    memory_server_url: str = "http://localhost:8080"
    memory_server_type: Literal["rest", "mcp"] = "rest"  # Protocol: REST API or MCP/SSE
    rag_server_url: str = "http://localhost:8000"
    rag_collection: str = "prismind"


@dataclass
class DocumentsConfig:
    """Document storage backend configuration.

    ``backend = "google"`` is the pre-Phase-1 behaviour and the rollback
    path; ``"filesystem"`` reads Markdown out of the Git clones under
    ``root`` (design §6.7).
    """
    backend: Literal["google", "filesystem"] = "google"
    root: str = "/srv/docs"
    repos_config: str = ""  # Empty = <root>/repos.toml
    work_root: str = "/srv/docs-work"  # Working tier (design 6.3.1)
    stale_after_days: float = 14.0
    # Infra placeholder registry (conventions §3.1). Empty =
    # <root>/spirrow-docs/docs/platform/infra-registry.md
    infra_registry: str = ""


@dataclass
class LogConfig:
    """Logging configuration."""
    level: str = "INFO"
    file: str = ""  # Empty = stdout
    format: str = "text"  # text / json


@dataclass
class SessionConfig:
    """Session configuration."""
    auto_save_interval: int = 20
    user_name: str = ""


#: Upper bound on the candidate text Prismind packs into one /v1/decide
#: ``state`` (``top_n * max_chars_per_candidate``). msg-001 puts the
#: upstream state limit at "~32K tokens"; Japanese text runs at roughly a
#: token per character, so 30 000 characters leaves room for the query and
#: the JSON framing. The value is Prismind's own guard, not a number
#: Lexora enforces (T-decide-rerank msg-005 B5).
RERANK_MAX_STATE_CHARS = 30_000


@dataclass
class RerankConfig:
    """Search-result re-ranking through Lexora ``/v1/decide``.

    T-decide-rerank: msg-001 (spec), msg-005 / msg-023 (design), and the
    human decision "B" that restored ``keep_k`` and ``has_answer``
    filtering from msg-001.
    """
    enabled: bool = False
    lexora_url: str = "http://localhost:8110"
    policy: str = "prismind.rerank"  # /v1/decide policy tag
    questions_version: str = "prismind.rerank/v1"
    top_n: int = 30  # candidates sent per request (questions are always top_n)
    keep_k: int = 8  # reranked candidates kept for the caller
    max_chars_per_candidate: int = 600
    timeout_s: float = 10.0
    min_noul: float = 0.35  # has_answer below this -> "no match"

    def validation_errors(self) -> list[str]:
        """Return every problem with this section (empty = valid)."""
        errors: list[str] = []
        if self.top_n < 1:
            errors.append(f"rerank.top_n must be at least 1 (got {self.top_n})")
        if not 1 <= self.keep_k <= max(self.top_n, 1):
            errors.append(
                f"rerank.keep_k must be between 1 and top_n={self.top_n} "
                f"(got {self.keep_k})"
            )
        if self.max_chars_per_candidate < 1:
            errors.append(
                "rerank.max_chars_per_candidate must be at least 1 "
                f"(got {self.max_chars_per_candidate})"
            )
        state_chars = self.top_n * self.max_chars_per_candidate
        if state_chars > RERANK_MAX_STATE_CHARS:
            errors.append(
                f"rerank.top_n * rerank.max_chars_per_candidate = {state_chars} "
                f"exceeds the state limit of {RERANK_MAX_STATE_CHARS} characters"
            )
        if not 0.0 <= self.min_noul <= 1.0:
            errors.append(f"rerank.min_noul must be within 0..1 (got {self.min_noul})")
        if self.timeout_s <= 0:
            errors.append(f"rerank.timeout_s must be positive (got {self.timeout_s})")
        if not self.policy:
            errors.append("rerank.policy must not be empty")
        if self.enabled and not self.lexora_url:
            errors.append("rerank.lexora_url is required when rerank.enabled = true")
        return errors

    @classmethod
    def from_dict(cls, data: dict) -> "RerankConfig":
        """Build the section and reject an invalid one at load time."""
        defaults = cls()
        config = cls(
            enabled=bool(data.get("enabled", defaults.enabled)),
            lexora_url=str(data.get("lexora_url", defaults.lexora_url)),
            policy=str(data.get("policy", defaults.policy)),
            questions_version=str(
                data.get("questions_version", defaults.questions_version)
            ),
            top_n=int(data.get("top_n", defaults.top_n)),
            keep_k=int(data.get("keep_k", defaults.keep_k)),
            max_chars_per_candidate=int(
                data.get("max_chars_per_candidate", defaults.max_chars_per_candidate)
            ),
            timeout_s=float(data.get("timeout_s", defaults.timeout_s)),
            min_noul=float(data.get("min_noul", defaults.min_noul)),
        )
        errors = config.validation_errors()
        if errors:
            raise ValueError("Invalid [rerank] configuration: " + "; ".join(errors))
        return config


@dataclass
class Config:
    """Application configuration."""
    google: GoogleConfig = field(default_factory=GoogleConfig)
    services: ServicesConfig = field(default_factory=ServicesConfig)
    documents: DocumentsConfig = field(default_factory=DocumentsConfig)
    log: LogConfig = field(default_factory=LogConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    rerank: RerankConfig = field(default_factory=RerankConfig)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from TOML file.

        Args:
            config_path: Path to config.toml file. If not provided,
                        searches in current directory and user home.

        Returns:
            Config instance
        """
        # Find config file
        if config_path:
            paths = [Path(config_path)]
        else:
            paths = [
                Path("config.toml"),
                Path.home() / ".config" / "spirrow-prismind" / "config.toml",
            ]

        config_file = None
        for p in paths:
            if p.exists():
                config_file = p
                break

        if config_file is None:
            # Return default config if no file found
            logger.info("No config file found, using defaults")
            return cls()

        # Parse TOML
        logger.info(f"Loading config from {config_file}")
        with open(config_file, "rb") as f:
            data = tomllib.load(f)

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        """Create config from dictionary."""
        return cls(
            google=GoogleConfig(
                credentials_path=data.get("google", {}).get(
                    "credentials_path", "credentials.json"
                ),
                token_path=data.get("google", {}).get("token_path", "token.json"),
                projects_folder_id=data.get("google", {}).get("projects_folder_id", ""),
            ),
            services=ServicesConfig(
                memory_server_url=data.get("services", {}).get(
                    "memory_server_url", "http://localhost:8080"
                ),
                memory_server_type=data.get("services", {}).get(
                    "memory_server_type", "rest"
                ),
                rag_server_url=data.get("services", {}).get(
                    "rag_server_url", "http://localhost:8000"
                ),
                rag_collection=data.get("services", {}).get(
                    "rag_collection", "prismind"
                ),
            ),
            documents=DocumentsConfig(
                backend=data.get("documents", {}).get("backend", "google"),
                root=data.get("documents", {}).get("root", "/srv/docs"),
                repos_config=data.get("documents", {}).get("repos_config", ""),
                work_root=data.get("documents", {}).get(
                    "work_root", "/srv/docs-work"
                ),
                stale_after_days=float(
                    data.get("documents", {}).get("stale_after_days", 14.0)
                ),
                infra_registry=data.get("documents", {}).get(
                    "infra_registry", ""
                ),
            ),
            log=LogConfig(
                level=data.get("log", {}).get("level", "INFO"),
                file=data.get("log", {}).get("file", ""),
                format=data.get("log", {}).get("format", "text"),
            ),
            session=SessionConfig(
                auto_save_interval=data.get("session", {}).get("auto_save_interval", 20),
                user_name=data.get("session", {}).get("user_name", ""),
            ),
            rerank=RerankConfig.from_dict(data.get("rerank", {})),
        )

    def validate(self) -> list[str]:
        """Validate configuration.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if self.log.level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            errors.append(f"Invalid log level: {self.log.level}")

        if self.log.format not in ["text", "json"]:
            errors.append(f"Invalid log format: {self.log.format}")

        if self.session.auto_save_interval < 1:
            errors.append("auto_save_interval must be at least 1")

        if self.documents.backend not in ["google", "filesystem"]:
            errors.append(
                f"Invalid documents.backend: {self.documents.backend} "
                "(must be 'google' or 'filesystem')"
            )

        if self.services.memory_server_type not in ["rest", "mcp"]:
            errors.append(f"Invalid memory_server_type: {self.services.memory_server_type} (must be 'rest' or 'mcp')")

        errors.extend(self.rerank.validation_errors())

        return errors

    def setup_logging(self) -> None:
        """Setup logging based on configuration."""
        level = getattr(logging, self.log.level.upper(), logging.INFO)
        
        handlers = []
        if self.log.file:
            handlers.append(logging.FileHandler(self.log.file))
        else:
            handlers.append(logging.StreamHandler())

        if self.log.format == "json":
            formatter = logging.Formatter(
                '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
                '"logger": "%(name)s", "message": "%(message)s"}'
            )
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )

        for handler in handlers:
            handler.setFormatter(formatter)

        logging.basicConfig(level=level, handlers=handlers)

    # Convenience properties for server
    @property
    def rag_url(self) -> str:
        """Get RAG server URL."""
        return self.services.rag_server_url

    @property
    def rag_collection(self) -> str:
        """Get RAG collection name."""
        return self.services.rag_collection

    @property
    def memory_url(self) -> str:
        """Get Memory server URL."""
        return self.services.memory_server_url

    @property
    def memory_type(self) -> Literal["rest", "mcp"]:
        """Get Memory server protocol type."""
        return self.services.memory_server_type

    @property
    def user_name(self) -> str:
        """Get user name."""
        return self.session.user_name

    @property
    def documents_backend(self) -> str:
        """Get the configured document storage backend."""
        return self.documents.backend

    @property
    def projects_folder_id(self) -> str:
        """Get projects root folder ID."""
        return self.google.projects_folder_id


def load_config(config_path: Optional[Path] = None) -> Config:
    """Load configuration from file.
    
    Args:
        config_path: Path to config file
        
    Returns:
        Config instance
    """
    return Config.load(str(config_path) if config_path else None)
