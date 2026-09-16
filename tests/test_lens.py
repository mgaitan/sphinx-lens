"""Tests for the portable semantic index."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest

from sphinx_lens import IndexMetadata, Lens, LensError, StaleIndexWarning
from sphinx_lens.lens import Entry, Link, TargetNotFoundError

if TYPE_CHECKING:
    from pathlib import Path

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
    path = lens.write(tmp_path / "_build" / "lens" / "index.json")
    loaded = Lens.open(tmp_path)
    assert loaded.source == lens.source
    assert loaded.entries == lens.entries
    assert loaded.links == lens.links
    assert loaded.metadata == lens.metadata
    assert loaded.index_path == path

    direct = lens.write(tmp_path / "portable" / "index.json")
    assert Lens.open(direct.parent).index_path == direct


def test_open_warns_when_local_sources_changed(lens: Lens, tmp_path: Path):
    """Provenance hashes reveal stale local indexes without blocking reads."""
    source = tmp_path / "source"
    source.mkdir()
    document = source / "guide.rst"
    document.write_text("current", encoding="utf-8")
    lens.source = "../source"
    lens.metadata = IndexMetadata(documents={"guide.rst": sha256(b"original").hexdigest()})
    index_path = lens.write(tmp_path / "artifact" / "index.json")

    with pytest.warns(StaleIndexWarning, match="1 source file"):
        Lens.open(index_path)

    lens.source = "../unavailable"
    unavailable_path = lens.write(tmp_path / "portable" / "index.json")
    assert Lens.open(unavailable_path).resolve("guide").title == "Guide"


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
    heading_match = lens.locate("time")[0]
    body_match = lens.locate("connection timeout", limit=1)[0]
    assert body_match.excerpt.startswith("Connection")
    token_match = lens.locate("timeout connection details", limit=1)[0]
    assert heading_match.score > body_match.score > token_match.score

    assert lens.locate("connection timeout", under={"api"}) == []
    assert lens.locate("connection timeout", under={"./guide"}, kinds={"section"})[0].entry.ref == "guide#timeouts"
    assert lens.locate("connection timeout", under={"guide"}, kinds={"section"})[0].entry.ref == "guide#timeouts"

    extra = Entry(
        ref="api#timeouts",
        kind="section",
        title="API timeouts",
        text="Connection timeout details",
        document="api",
        anchor="timeouts",
    )
    combined = Lens(source=lens.source, entries=[*lens.entries, extra], links=[])
    assert {result.entry.document for result in combined.locate("connection timeout", under={"guide", "api"})} == {
        "api",
        "guide",
    }


def test_locate_folds_accents_and_stems():
    """Supported Sphinx languages make accent and inflection variants searchable."""
    spanish = Lens(
        source=".",
        entries=[
            Entry(
                ref="guide",
                kind="document",
                title="Depósito y copiar usuarios",
                text="Cómo copiar un grupo de usuarios.",
                document="guide",
            )
        ],
        links=[],
        metadata=IndexMetadata(language="es"),
    )

    assert [result.entry.ref for result in spanish.locate("deposito")] == ["guide"]
    assert [result.entry.ref for result in spanish.locate("depósito")] == ["guide"]
    assert [result.entry.ref for result in spanish.locate("copio")] == ["guide"]


def test_locate_regex_and_filters(lens: Lens):
    """Regex search composes with semantic kind and domain filters."""
    exact = lens.locate(r"timeout(s)?", regex=True, kinds={"section"})
    assert exact[0].score == 1.0
    assert exact[0].entry.ref == "guide#timeouts"

    body = lens.locate(r"connection\s+timeout", regex=True, kinds={"section"})
    assert body[0].score < exact[0].score
    assert body[0].excerpt.startswith("Connection")

    objects = lens.locate(r"client", regex=True, kinds={"object"}, domain="py")
    assert [result.entry.ref for result in objects] == ["py:class:demo.Client"]
    assert lens.locate(r"^demo\.Client$", regex=True, kinds={"object"})[0].score == 1.0
    assert lens.locate("client", domain="std") == []

    with pytest.raises(LensError, match="Invalid regular expression"):
        lens.locate("[", regex=True)


def test_locate_collapses_entries_at_the_same_location(lens: Lens):
    """Search results keep one semantic entry per physical location."""
    duplicate = Entry(
        ref="std:label:timeouts",
        kind="object",
        title="Timeouts",
        text="Connection timeout details",
        document="guide",
        anchor="timeouts",
        domain="std",
        object_type="label",
        name="timeouts",
    )
    index = Lens(source=lens.source, entries=[*lens.entries, duplicate], links=[])

    results = index.locate("timeouts")

    assert [result.entry.location for result in results].count("guide#timeouts") == 1


def test_locate_excerpt_boundaries():
    """Search marks body text clipped on either side of a match."""
    text = f"{'before ' * 40}needle {'after ' * 40}"
    index = Lens(source=".", entries=[Entry("long", "document", "Long", text, "long")], links=[])

    excerpt = index.locate("needle")[0].excerpt

    assert excerpt.startswith("...")
    assert excerpt.endswith("...")


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
    assert lens.read("guide").startswith("Alpha beta gamma\n\nConnection timeout details")
