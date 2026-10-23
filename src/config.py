"""Runtime configuration for the knowledge engine.

The engine lives in the master repo and scans external target repositories. A
:class:`RepoTarget` names one repo (its label and absolute root); :class:`Settings`
holds the AWS/model/store settings plus the list of targets. Everything the
chunker, embedder, store, MCP server and agent need reads from one typed object
instead of reaching into ``os.environ``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Master repo root — this file is <root>/src/config.py, so two parents up.
ROOT_DIR = Path(__file__).resolve().parent.parent

# Base path shared by every developer machine, so a target can be given as a
# path relative to it instead of an absolute one.
WEBSERVICES_BASE = Path("C:/WebServices")

# The repos the engine indexes, as paths relative to C:/WebServices. Override
# with REPOMAP_TARGETS (JSON) to change the set without editing code.
#
# For cae-ai-agents only the strut-calc agent subtree is indexed, and for
# cae-docker-images only the strut-calc-v2 solver, per the user's scope: those
# monorepos hold unrelated apps the StrutCalc knowledge base should not pull in.
DEFAULT_TARGETS: tuple[dict[str, str], ...] = (
    {
        "label": "strut-calc",
        "root": "cae-apps/Apps/StrutCalc",
    },
    {
        "label": "cae-ai-agents",
        "root": "cae-ai-agents/agents/strut-calc",
    },
    {
        "label": "cae-engine",
        "root": "cae-engine",
    },
    {
        "label": "strut-calc-v2",
        "root": "cae-docker-images/strut-calc-v2",
    },
)


class RepoTarget(BaseModel):
    """One repository the engine scans.

    Attributes:
        label: Short, stable name stored on every chunk from this repo.
        root: Absolute path to the repo root. A relative value is resolved
            against ``C:/WebServices``.
    """

    label: str
    root: Path

    @field_validator("root")
    @classmethod
    def _resolve_root(cls, value: Path) -> Path:
        """Resolve a relative root against the shared base path.

        Args:
            value: Root path as given, absolute or relative.

        Returns:
            Absolute root path.
        """
        return value if value.is_absolute() else (WEBSERVICES_BASE / value)


class Settings(BaseSettings):
    """Typed settings for the knowledge engine.

    Attributes:
        aws_profile: AWS profile name resolved from ``~/.aws``.
        aws_region: Region for the Bedrock runtime client.
        embed_model_id: Bedrock embedding model id.
        embed_dim: Embedding dimensionality, must match the model.
        agent_model_id: Bedrock chat model id for the strands-compose agent.
        db_path: Vector store path, relative to the master root unless absolute.
        mcp_host: MCP server bind host.
        mcp_port: MCP server bind port.
        search_k: Default number of results a search returns.
        targets_raw: JSON override for the scanned repos, or empty for defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    aws_profile: str = Field(default="default", alias="AWS_PROFILE")
    aws_region: str = Field(default="eu-central-1", alias="AWS_REGION")

    embed_model_id: str = Field(
        default="amazon.titan-embed-text-v2:0", alias="REPOMAP_EMBED_MODEL_ID"
    )
    embed_dim: int = Field(default=1024, alias="REPOMAP_EMBED_DIM")

    agent_model_id: str = Field(
        default="us.anthropic.claude-haiku-4-5-v1:0", alias="REPOMAP_AGENT_MODEL_ID"
    )

    db_path: str = Field(default="index.db", alias="REPOMAP_DB_PATH")

    mcp_host: str = Field(default="127.0.0.1", alias="REPOMAP_MCP_HOST")
    mcp_port: int = Field(default=9100, alias="REPOMAP_MCP_PORT")

    search_k: int = Field(default=6, alias="REPOMAP_SEARCH_K")

    targets_raw: str = Field(default="", alias="REPOMAP_TARGETS")

    @property
    def targets(self) -> list[RepoTarget]:
        """Return the repositories the engine scans.

        Reads ``REPOMAP_TARGETS`` as a JSON array of ``{label, root}`` objects
        when set, otherwise falls back to :data:`DEFAULT_TARGETS`.

        Returns:
            The configured repo targets.

        Raises:
            ValueError: When ``REPOMAP_TARGETS`` is set but not a JSON array of
                objects.
        """
        if not self.targets_raw.strip():
            return [_build_target(entry) for entry in DEFAULT_TARGETS]
        try:
            parsed = json.loads(self.targets_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"REPOMAP_TARGETS is not valid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise ValueError("REPOMAP_TARGETS must be a JSON array of {label, root}")
        return [_build_target(entry) for entry in parsed]

    @property
    def resolved_db_path(self) -> Path:
        """Return the vector store path as an absolute path.

        Returns:
            ``db_path`` resolved against the master root when it is relative.
        """
        candidate = Path(self.db_path)
        return candidate if candidate.is_absolute() else (ROOT_DIR / candidate)


def _build_target(entry: dict[str, str]) -> RepoTarget:
    """Build a :class:`RepoTarget` from a ``{label, root}`` mapping.

    Pydantic coerces the string ``root`` into a ``Path`` and the validator
    resolves it. A wrapper keeps that coercion in one typed place.

    Args:
        entry: Mapping with ``label`` and ``root`` keys.

    Returns:
        The validated repo target.

    Raises:
        KeyError: When ``label`` or ``root`` is missing.
    """
    return RepoTarget(label=entry["label"], root=Path(entry["root"]))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Returns:
        The cached :class:`Settings` instance.
    """
    return Settings()
