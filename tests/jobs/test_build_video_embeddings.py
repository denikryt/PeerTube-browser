"""Regression tests for the semantic text used to build video embeddings."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
JOB = ROOT / "engine" / "server" / "db" / "jobs" / "build-video-embeddings.py"


def _load() -> Any:
    """Load the hyphenated embedding job as a module for pure-function tests."""
    spec = importlib.util.spec_from_file_location("build_video_embeddings_job", JOB)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(**overrides: object) -> dict[str, object]:
    """Return one representative video row accepted by ``build_text``."""
    row: dict[str, object] = {
        "title": "Title",
        "description": "Description",
        "tags_json": '["tag-one", "tag-two"]',
        "category": "Music",
        "channel_name": "Channel",
        "comments_count": 7,
    }
    row.update(overrides)
    return row


def test_build_text_contains_only_semantic_video_fields() -> None:
    """The embedding input contains semantic content fields and their labels."""
    mod = _load()

    text = mod.build_text(_row())

    assert text == (
        "Title\nDescription\ntags: tag-one, tag-two\n"
        "category: Music\nchannel: Channel"
    )


def test_build_text_does_not_depend_on_comments_count() -> None:
    """A volatile comments counter must not change a video's semantic text."""
    mod = _load()

    assert mod.build_text(_row(comments_count=1)) == mod.build_text(
        _row(comments_count=9999)
    )


def test_build_text_returns_none_when_semantic_fields_are_empty() -> None:
    """Rows without semantic content keep the existing skip behavior."""
    mod = _load()

    assert mod.build_text(
        _row(
            title=None,
            description=None,
            tags_json=None,
            category=None,
            channel_name=None,
            comments_count=123,
        )
    ) is None
