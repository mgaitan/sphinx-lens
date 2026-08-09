"""Integration tests for extracting Sphinx semantics."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from docutils import nodes
from docutils.utils import new_document
from sphinx import addnodes
from sphinx.application import Sphinx
from sphinx.errors import ConfigError

from sphinx_lens import BuildError, Lens, build, extractor

if TYPE_CHECKING:
    from pathlib import Path

    from sphinx.environment import BuildEnvironment

DOCUMENT_COUNT = 3


def test_build_extracts_semantics(sphinx_project: Path):
    """A Sphinx build becomes a portable document, object, and link index."""
    lens = build(sphinx_project)

    assert lens.index_path == sphinx_project / "_build" / "lens" / "index.json"
    assert len([entry for entry in lens.entries if entry.kind == "document"]) == DOCUMENT_COUNT
    assert {entry.ref for entry in lens.children("guide")} == {
        "guide#connection-timeout",
        "guide#glossary",
        "guide#retry-policy",
    }
    client = lens.resolve("py:class", "demo.Client")
    method = lens.resolve("demo.Client.connect")
    assert client.text.startswith("class demo.Client")
    assert "connect()" not in client.text
    assert method.parent == client.ref
    assert method.text.startswith("connect()")
    assert lens.read("std:term:connection budget") == (
        "connection budget\n\nThe total time allowed for connection attempts."
    )

    client_links = lens.linked(client.ref)
    assert {link.source for link in client_links.incoming} == {"index", "guide#connection-timeout"}
    assert client_links.outgoing[0].target == "guide"

    guide_links = lens.linked("guide#connection-timeout").outgoing
    assert ("guide#retry-policy", "internal") in {(link.target, link.kind) for link in guide_links}
    assert ("https://python.org", "external") in {(link.target, link.kind) for link in guide_links}
    assert ("guide", "internal") in {(link.target, link.kind) for link in guide_links}
    assert any(link.kind == "unresolved" for link in lens.linked("index").outgoing)

    reopened = Lens.open(sphinx_project)
    assert reopened.entries == lens.entries


def test_build_to_explicit_output(sphinx_project: Path, tmp_path: Path):
    """The artifact location can live outside the Sphinx source tree."""
    output = tmp_path / "artifact" / "lens"
    lens = build(sphinx_project, output)
    assert lens.index_path == output / "index.json"
    assert lens.index_path.is_file()


def test_sphinx_builder(sphinx_project: Path, tmp_path: Path):
    """Sphinx can produce the index as a native builder artifact."""
    output = tmp_path / "lens"
    app = Sphinx(
        srcdir=sphinx_project,
        confdir=sphinx_project,
        outdir=output,
        doctreedir=tmp_path / "doctrees",
        buildername="lens",
        freshenv=True,
    )
    app.build(force_all=True)

    assert app.statuscode == 0
    assert isinstance(app.builder, extractor.LensBuilder)
    assert Lens.open(output).resolve("demo.Client").kind == "object"


def test_failed_sphinx_build(sphinx_project: Path, mocker):
    """A failed Sphinx status becomes a concise API error."""
    app = mocker.Mock(statuscode=1)

    def fake_sphinx(**kwargs: Any):
        kwargs["warning"].write("broken project")
        return app

    mocker.patch("sphinx_lens.extractor.Sphinx", side_effect=fake_sphinx)
    with pytest.raises(BuildError, match="broken project"):
        build(sphinx_project, fail_on_warning=True)


def test_sphinx_exception_becomes_build_error(sphinx_project: Path, mocker):
    """Configuration failures do not expose a raw Sphinx traceback."""
    mocker.patch("sphinx_lens.extractor.Sphinx", side_effect=ConfigError("invalid configuration"))

    with pytest.raises(BuildError, match="invalid configuration"):
        build(sphinx_project)


def test_fail_on_warning(sphinx_project: Path):
    """Strict builds fail when Sphinx reports a documentation warning."""
    conf = sphinx_project / "conf.py"
    conf.write_text(f"{conf.read_text(encoding='utf-8')}\nnitpicky = True\n", encoding="utf-8")

    with pytest.raises(BuildError, match="Missing"):
        build(sphinx_project, fail_on_warning=True)


def test_git_metadata_without_git(sphinx_project: Path, mocker):
    """A portable build does not require the Git executable."""
    mocker.patch("sphinx_lens.extractor.subprocess.run", side_effect=FileNotFoundError)

    lens = build(sphinx_project)

    assert lens.metadata.git_commit is None


def test_fixture_search_relevance(sphinx_project: Path):
    """Representative concept and API queries put the expected target in the top three."""
    lens = build(sphinx_project)
    cases = {
        "connection timeout": "guide#connection-timeout",
        "retry policy": "guide#retry-policy",
        "connection budget": "std:term:connection budget",
        "network client": "py:class:demo.Client",
        "connect to service": "py:method:demo.Client.connect",
        "demo.Client": "py:class:demo.Client",
        "total time allowed": "std:term:connection budget",
        "Retry twice": "guide#retry-policy",
        "Guide": "guide",
        "Client(timeout=30)": "py:class:demo.Client",
    }

    for query, expected_ref in cases.items():
        assert expected_ref in {result.entry.ref for result in lens.locate(query, limit=3)}


def test_unusual_doctree_nodes():
    """Incomplete extension nodes degrade to useful fallback metadata."""
    document = new_document("generated")
    document += nodes.section()
    untitled = nodes.section(ids=["generated"])
    document += untitled
    signature = addnodes.desc_signature(ids=["loose-object"])
    signature += nodes.Text("loose signature")
    document += signature
    app = SimpleNamespace(env=SimpleNamespace(titles={}))
    anchor_parents: dict[tuple[str, str], str] = {}
    anchor_texts: dict[tuple[str, str], str] = {}

    entries = extractor._document_entries(
        cast("BuildEnvironment", app.env),
        "fallback",
        document,
        anchor_parents,
        anchor_texts,
    )

    assert entries[0].title == "fallback"
    assert entries[1].title == "generated"
    assert anchor_texts[("fallback", "loose-object")] == "loose signature"


def test_reference_edge_cases():
    """Raw references and unusual toctrees are classified predictably."""
    assert extractor._reference_target("guide", nodes.reference(refid="local")) == (
        "guide#local",
        "internal",
    )
    assert extractor._reference_target("guide", nodes.reference()) == ("", "unresolved")

    raw_document = new_document("references")
    missing_xref = addnodes.pending_xref(refdomain="doc", reftype="myst", reftarget="missing")
    missing_xref += nodes.inline("", "missing")
    raw_document += missing_xref
    resolved_document = new_document("references-resolved")
    resolved_document += nodes.reference("", "empty")
    resolved_document += nodes.reference("", "missing", refuri="missing.html#part")
    description = addnodes.desc()
    content = addnodes.desc_content()
    content += nodes.reference("", "nested", refuri="nested.html")
    description += content
    resolved_document += description
    toctree = addnodes.toctree()
    toctree["entries"] = [("This page", "self"), ("External", "https://example.com"), (None, "guide")]
    raw_document += toctree

    links = list(
        extractor._document_links(
            "index",
            raw_document,
            resolved_document,
            {},
            {"index", "guide"},
        )
    )

    assert {(link.target, link.kind) for link in links} == {
        ("missing#part", "unresolved"),
        ("nested", "unresolved"),
        ("guide", "internal"),
    }


def test_resolved_xrefs_and_root_relative_paths():
    """Sphinx-resolved references retain destinations across domains."""
    raw = new_document("raw")
    xref = addnodes.pending_xref(refdomain="doc", reftype="myst", reftarget="guide")
    xref += nodes.inline("", "Guide")
    raw += xref
    resolved = new_document("resolved")
    resolved += nodes.reference("", "Guide", refuri="guide")

    links = list(extractor._document_links("index", raw, resolved, {}, {"index", "guide"}))

    assert links == [extractor.Link(source="index", target="guide", label="Guide", kind="internal")]
    assert extractor._reference_target("guide/page", nodes.reference(refuri="/api.html#client")) == (
        "api#client",
        "internal",
    )
