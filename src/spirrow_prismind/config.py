"""Configuration management for Spirrow-Prismind."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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
    rag_server_url: str = "http://localhost:8000"
    rag_collection: str = "prismind"


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


@dataclass
class Config:
    """Application configuration."""
    google: GoogleConfig = field(default_factory=GoogleConfig)
    services: ServicesConfig = field(default_factory=ServicesConfig)
    log: LogConfig = field(default_factory=LogConfig)
    session: SessionConfig = field(default_factory=SessionConfig)

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
                rag_server_url=data.get("services", {}).get(
                    "rag_server_url", "http://localhost:8000"
                ),
                rag_collection=data.get("services", {}).get(
                    "rag_collection", "prismind"
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
    def user_name(self) -> str:
        """Get user name."""
        return self.session.user_name

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
