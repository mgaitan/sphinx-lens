"""Tests for the portable semantic index."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sphinx_lens import Lens, LensError
from sphinx_lens.lens import Entry, Link, TargetNotFoundError

if TYPE_CHECKING:
    from pathlib import Path

HEADING_SCORE = 0.9
BODY_SCORE = 0.7
MIN_TOKEN_SCORE = 0.4
MAX_TOKEN_SCORE = 0.6
REFERENCE_COUNT = 2


@pytest.fixture
def lens(tmp_path: Path) -> Lens:
    """Return an in-memory Lens covering query edge cases."""
    entries = [
        Entry(ref="guide", kind="document", title="Guide", text="Alpha beta gamma", document="guide"),
        Entry(
            ref="guide#timeouts",
            kind="section",
            title="Timeouts",
            text="Connection timeout details " * 20,
            document="guide",
            anchor="timeouts",
            parent="guide",
        ),
        Entry(
            ref="py:class:demo.Client",
            kind="object",
            title="demo.Client",
            text="Client API",
            document="api",
            anchor="demo.Client",
            parent="api",
            domain="py",
            object_type="class",
            name="demo.Client",
        ),
    ]
    links = [
        Link(source="guide#timeouts", target="api#demo.Client", label="client", kind="internal"),
        Link(source="guide#timeouts", target="https://example.com", label="web", kind="external"),
    ]
    return Lens(source=str(tmp_path), entries=entries, links=links)


def test_round_trip_and_discovery(lens: Lens, tmp_path: Path):
    """Indexes serialize and load from files and conventional directories."""
    path = lens.write(tmp_path / ".sphinx-lens" / "index.json")
    loaded = Lens.open(tmp_path)
    assert loaded.source == lens.source
    assert loaded.entries == lens.entries
    assert loaded.links == lens.links
    assert loaded.index_path == path

    direct = lens.write(tmp_path / "portable" / "index.json")
    assert Lens.open(direct.parent).index_path == direct


def test_open_errors(tmp_path: Path):
    """Missing and incompatible indexes have actionable errors."""
    with pytest.raises(LensError, match="index not found"):
        Lens.open(tmp_path)

    path = tmp_path / "index.json"
    path.write_text(json.dumps({"version": 999}), encoding="utf-8")
    with pytest.raises(LensError, match="Unsupported"):
        Lens.open(path)


def test_resolve(lens: Lens):
    """Locations, names, and domain-object pairs resolve to entries."""
    assert lens.resolve("guide").title == "Guide"
    assert lens.resolve("demo.Client").ref == "py:class:demo.Client"
    assert lens.resolve("py:class", "demo.Client").location == "api#demo.Client"
    with pytest.raises(TargetNotFoundError):
        lens.resolve("missing")


def test_ambiguous_resolve(lens: Lens):
    """Ambiguous short object names report their candidates."""
    duplicate = Entry(
        ref="js:class:demo.Client",
        kind="object",
        title="demo.Client",
        text="",
        document="js-api",
        domain="js",
        object_type="class",
        name="demo.Client",
    )
    ambiguous = Lens(source=lens.source, entries=[*lens.entries, duplicate], links=[])
    with pytest.raises(LensError, match="Ambiguous target"):
        ambiguous.resolve("demo.Client")


def test_locate(lens: Lens):
    """Search ranks headings, body phrases, token matches, and fuzzy names."""
    assert lens.locate("") == []
    assert lens.locate("guide")[0].score == 1.0
    assert lens.locate("time")[0].score == HEADING_SCORE
    body_match = lens.locate("connection timeout", limit=1)[0]
    assert body_match.score == BODY_SCORE
    assert body_match.excerpt.startswith("Connection")
    token_match = lens.locate("timeout connection details", limit=1)[0]
    assert MIN_TOKEN_SCORE < token_match.score < MAX_TOKEN_SCORE


def test_excerpt_boundaries():
    """Long excerpts mark clipped text on either side."""
    text = f"{'before ' * 40}needle {'after ' * 40}"
    excerpt = Lens._excerpt(text, "needle", width=60)
    assert excerpt.startswith("...")
    assert excerpt.endswith("...")
    assert Lens._excerpt("No exact phrase", "absent") == "No exact phrase"


def test_navigation(lens: Lens):
    """Children and links navigate the semantic hierarchy."""
    assert [entry.ref for entry in lens.children("guide")] == ["guide#timeouts"]
    assert lens.children("guide#timeouts") == ()
    references = lens.references("guide")
    assert len(references) == REFERENCE_COUNT
    linked = lens.linked("py:class:demo.Client")
    assert len(linked.incoming) == 1
    assert linked.outgoing == ()
    assert lens.inspect("guide") == lens.resolve("guide")
    assert lens.read("guide") == "Alpha beta gamma"
