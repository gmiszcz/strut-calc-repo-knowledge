"""Tests for configuration and repo-target resolution."""

from __future__ import annotations

from pathlib import Path

from src.config import Settings


def test_default_targets_cover_the_four_repos() -> None:
    settings = Settings(REPOMAP_TARGETS="")
    labels = [t.label for t in settings.targets]
    assert labels == ["strut-calc", "cae-ai-agents", "cae-engine", "strut-calc-v2"]
    assert all(t.root.is_absolute() for t in settings.targets)


def test_relative_target_root_resolves_against_webservices() -> None:
    settings = Settings(REPOMAP_TARGETS='[{"label":"x","root":"cae-engine"}]')
    target = settings.targets[0]
    assert target.root == Path("C:/WebServices/cae-engine")


def test_absolute_target_root_is_kept() -> None:
    settings = Settings(REPOMAP_TARGETS='[{"label":"x","root":"D:/elsewhere/repo"}]')
    assert settings.targets[0].root == Path("D:/elsewhere/repo")


def test_resolved_db_path_is_absolute() -> None:
    assert Settings(REPOMAP_DB_PATH="index.db").resolved_db_path.is_absolute()
