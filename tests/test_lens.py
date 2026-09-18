"""Tests for the portable semantic index."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import closing
from hashlib import sha256
from importlib.metadata import version
from typing import TYPE_CHECKING

import pytest

from sphinx_lens import IndexMetadata, Lens, LensError, StaleIndexWarning, discover_source
from sphinx_lens.lens import DocumentInfo, Entry, Link, TargetNotFoundError, _search_language, _term_coverage

if TYPE_CHECKING:
    from pathlib import Path

REFERENCE_COUNT = 2
NEW_INDEX_MODE = 0o640
SHARED_INDEX_MODE = 0o664


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
    return Lens(
        source=str(tmp_path),
        entries=entries,
        links=links,
        documents={
            "guide": DocumentInfo(title="Guide", metadata={"audience": "developers"}),
            "api": DocumentInfo(title="API", metadata={"audience": "developers"}),
        },
    )


def test_round_trip_and_discovery(lens: Lens, tmp_path: Path):
    """Indexes serialize and load from files and conventional directories."""
    path = lens.write(tmp_path / "_build" / "lens" / "index.sqlite")
    loaded = Lens.open(tmp_path)
    assert loaded.source == lens.source
    assert loaded.entries == lens.entries
    assert loaded.links == lens.links
    assert loaded.metadata == lens.metadata
    assert loaded.documents == lens.documents
    assert loaded.index_path == path

    direct = lens.write(tmp_path / "portable" / "index.sqlite")
    assert Lens.open(direct.parent).index_path == direct


def test_sqlite_locate_uses_fts_without_loading_all_entries(lens: Lens, tmp_path: Path):
    """Normal text search keeps the complete entries table lazy."""
    with pytest.raises(LensError, match="no SQLite artifact"), lens._connect():
        pass

    loaded = Lens.open(lens.write(tmp_path / "index.sqlite"))

    assert loaded._entries is None
    assert loaded.locate("connection timeout")[0].entry.ref == "guide#timeouts"
    assert loaded.locate("!!!") == []
    assert loaded._entries is None


def test_sqlite_locate_preserves_infix_matches(lens: Lens, tmp_path: Path):
    """Trigram candidates preserve partial-word searches after persistence."""
    loaded = Lens.open(lens.write(tmp_path / "index.sqlite"))

    assert [result.entry.ref for result in loaded.locate("nection")] == ["guide#timeouts"]
    assert [result.entry.ref for result in loaded.locate("nection details")] == ["guide#timeouts"]
    assert loaded._entries is None


def test_sqlite_schema_has_structural_indexes(lens: Lens, tmp_path: Path):
    """The artifact indexes canonical, hierarchy, and link lookups."""
    path = lens.write(tmp_path / "index.sqlite")

    with closing(sqlite3.connect(path)) as connection:
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {"entries_document_order", "entries_parent_order", "links_source", "links_target"} <= indexes
    assert {"entries_fts", "entries_trigram"} <= tables


def test_write_preserves_readable_permissions(lens: Lens, tmp_path: Path):
    """New indexes honor the umask and replacements retain the existing mode."""
    previous_umask = os.umask(0o027)
    try:
        path = lens.write(tmp_path / "index.sqlite")
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(path.stat().st_mode) == NEW_INDEX_MODE

    path.chmod(SHARED_INDEX_MODE)
    lens.write(path)
    assert stat.S_IMODE(path.stat().st_mode) == SHARED_INDEX_MODE


def test_write_retries_a_temporary_name_collision(lens: Lens, tmp_path: Path, mocker):
    """Atomic writes choose another temporary name after a collision."""
    collision = tmp_path / ".index.sqlite.collision.tmp"
    collision.touch()
    mocker.patch("sphinx_lens.lens.secrets.token_hex", side_effect=["collision", "available"])

    assert lens.write(tmp_path / "index.sqlite").is_file()


def test_open_keeps_an_absolute_database_path(lens: Lens, tmp_path: Path, monkeypatch):
    """Lazy reads survive a working-directory change after a relative open."""
    monkeypatch.chdir(tmp_path)
    lens.write("index.sqlite")
    loaded = Lens.open("index.sqlite")
    monkeypatch.chdir(tmp_path.parent)

    assert loaded.index_path == tmp_path / "index.sqlite"
    assert loaded.resolve("guide").title == "Guide"
    assert loaded.locate("nection")[0].entry.ref == "guide#timeouts"


def test_failed_write_keeps_previous_artifact(lens: Lens, tmp_path: Path, mocker):
    """A write failure leaves the last complete database in place."""
    path = lens.write(tmp_path / "index.sqlite")
    original = path.read_bytes()
    mocker.patch.object(lens, "_write_database", side_effect=RuntimeError("interrupted"))

    with pytest.raises(RuntimeError, match="interrupted"):
        lens.write(path)

    assert path.read_bytes() == original


def test_discovery_finds_a_sphinx_project(lens: Lens, tmp_path: Path):
    """Discovery follows conf.py from the repository root or a nested source path."""
    source = tmp_path / "knowledge"
    nested = source / "guide"
    nested.mkdir(parents=True)
    (source / "conf.py").touch()
    path = lens.write(source / "_build" / "lens" / "index.sqlite")

    assert Lens.open(tmp_path).index_path == path
    assert Lens.open(nested).index_path == path
    assert discover_source(tmp_path) == source
    assert discover_source(nested) == source

    other_source = tmp_path / "docs"
    other_source.mkdir()
    (other_source / "conf.py").touch()
    with pytest.raises(LensError, match="Multiple Sphinx source directories"):
        discover_source(tmp_path)


def test_discover_source_errors_without_conf(tmp_path: Path):
    """Source discovery reports when no nearby Sphinx project exists."""
    with pytest.raises(LensError, match=r"conf\.py not found"):
        discover_source(tmp_path)


def test_open_warns_when_local_sources_changed(lens: Lens, tmp_path: Path):
    """Provenance hashes reveal stale local indexes without blocking reads."""
    source = tmp_path / "source"
    source.mkdir()
    document = source / "guide.rst"
    document.write_text("current", encoding="utf-8")
    lens.source = "../source"
    lens.metadata = IndexMetadata(documents={"guide.rst": sha256(b"original").hexdigest()})
    index_path = lens.write(tmp_path / "artifact" / "index.sqlite")

    with pytest.warns(StaleIndexWarning, match="1 source file"):
        Lens.open(index_path)

    lens.source = "../unavailable"
    unavailable_path = lens.write(tmp_path / "portable" / "index.sqlite")
    assert Lens.open(unavailable_path).resolve("guide").title == "Guide"

    lens.source = None
    portable_path = lens.write(tmp_path / "portable-no-source" / "index.sqlite")
    with pytest.warns(StaleIndexWarning, match="cannot be checked"):
        Lens.open(portable_path)


def test_open_errors(tmp_path: Path, mocker):
    """Missing and incompatible indexes have actionable errors."""
    with pytest.raises(LensError, match="index not found"):
        Lens.open(tmp_path)

    legacy = tmp_path / "index.json"
    legacy.write_text(json.dumps({"version": 4}), encoding="utf-8")
    with pytest.raises(LensError, match=r"JSON.*no longer supported.*rebuild"):
        Lens.open(legacy)
    with pytest.raises(LensError, match=r"JSON.*no longer supported.*rebuild"):
        Lens.open(tmp_path)

    path = tmp_path / "incompatible.sqlite"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE artifact (schema_version INTEGER)")
        connection.execute("INSERT INTO artifact VALUES (999)")
    with pytest.raises(LensError, match=r"Unsupported.*rebuild"):
        Lens.open(path)

    empty = tmp_path / "empty.sqlite"
    with closing(sqlite3.connect(empty)) as connection, connection:
        connection.execute("CREATE TABLE artifact (schema_version INTEGER)")
    with pytest.raises(LensError, match="missing artifact metadata"):
        Lens.open(empty)

    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_text("not a database", encoding="utf-8")
    with pytest.raises(LensError, match="Invalid Lens SQLite index"):
        Lens.open(corrupt)

    unreadable = tmp_path / "unreadable.sqlite"
    unreadable.touch()
    mocker.patch("sphinx_lens.lens.sqlite3.connect", side_effect=sqlite3.OperationalError("denied"))
    with pytest.raises(LensError, match=r"Cannot open Lens index.*denied"):
        Lens.open(unreadable)


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
    assert _term_coverage(set(), "heading", "body", None) == (0.0, 0.0)
    assert Lens._search_score("needle", "unrelated", "", exact=False) > 0

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
    assert spanish.locate("!!!") == []

    language = _search_language("es")
    assert language is not None
    assert version("pystemmer")
    assert language.stem("copiar") == "copi"

    accented = Lens(
        source=".",
        entries=[
            Entry(
                ref="coffee",
                kind="document",
                title="Café setup",
                text="A concise guide.",
                document="coffee",
            ),
            Entry(
                ref="body",
                kind="document",
                title="Other guide",
                text="The café is useful.",
                document="body",
            ),
        ],
        links=[],
    )
    results = accented.locate("cafe")
    assert results[0].entry.ref == "coffee"
    assert results[1].entry.ref == "body"
    assert results[0].score > results[1].score
    assert results[1].excerpt.startswith("The café")


def test_locate_excerpt_centers_a_stemmed_match():
    """Stemmed searches show the matching display word rather than the scope start."""
    spanish = Lens(
        source=".",
        entries=[
            Entry(
                ref="guide",
                kind="document",
                title="Guide",
                text=f"{'Introducción. ' * 30}Cómo copiar un grupo de usuarios.",
                document="guide",
            )
        ],
        links=[],
        metadata=IndexMetadata(language="es"),
    )

    excerpt = spanish.locate("copio")[0].excerpt

    assert excerpt.startswith("...")
    assert "Cómo copiar un grupo" in excerpt


def test_document_metadata_resolves_from_any_entry(lens: Lens):
    """Document metadata is available for document, section, and object targets."""
    assert lens.document_metadata("guide") == {"audience": "developers"}
    assert lens.document_metadata("guide#timeouts") == {"audience": "developers"}
    assert lens.document_metadata("py:class:demo.Client") == {"audience": "developers"}


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

    assert index.document_metadata("long") == {}
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
