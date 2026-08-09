"""Integration tests for extracting Sphinx semantics."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from docutils import nodes
from docutils.utils import new_document
from sphinx import addnodes

from sphinx_lens import Lens, build, extractor

if TYPE_CHECKING:
    from pathlib import Path

    from sphinx.application import Sphinx

DOCUMENT_COUNT = 3


def test_build_extracts_semantics(sphinx_project: Path):
    """A Sphinx build becomes a portable document, object, and link index."""
    lens = build(sphinx_project)

    assert lens.index_path == sphinx_project / ".sphinx-lens" / "index.json"
    assert len([entry for entry in lens.entries if entry.kind == "document"]) == DOCUMENT_COUNT
    assert {entry.ref for entry in lens.children("guide")} == {
        "guide#connection-timeout",
        "guide#retry-policy",
    }
    client = lens.resolve("py:class", "demo.Client")
    method = lens.resolve("demo.Client.connect")
    assert client.text.startswith("class demo.Client")
    assert method.parent == client.ref
    assert method.text.startswith("connect()")

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
    output = tmp_path / "artifact" / "lens.json"
    lens = build(sphinx_project, output)
    assert lens.index_path == output
    assert output.is_file()


def test_failed_sphinx_build(sphinx_project: Path, mocker):
    """A failed Sphinx status becomes a concise API error."""
    app = mocker.Mock(statuscode=1)

    def fake_sphinx(**kwargs: Any):
        kwargs["warning"].write("broken project")
        return app

    mocker.patch("sphinx_lens.extractor.Sphinx", side_effect=fake_sphinx)
    with pytest.raises(RuntimeError, match="broken project"):
        build(sphinx_project)


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

    entries = extractor._document_entries(cast("Sphinx", app), "fallback", document, anchor_parents, anchor_texts)

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

    document = new_document("references")
    document += nodes.reference("", "empty")
    document += nodes.reference("", "missing", refuri="missing.html#part")
    description = addnodes.desc()
    content = addnodes.desc_content()
    content += nodes.reference("", "nested", refuri="nested.html")
    description += content
    document += description
    toctree = addnodes.toctree()
    toctree["entries"] = [("This page", "self"), ("External", "https://example.com"), (None, "guide")]
    document += toctree

    resolution = extractor.ResolutionContext(known_locations={"index", "guide"}, domain_objects=[], role_types={})
    links = list(extractor._document_links("index", document, {}, resolution))

    assert {(link.target, link.kind) for link in links} == {
        ("missing#part", "unresolved"),
        ("nested", "unresolved"),
        ("guide", "internal"),
    }


def test_xref_role_mapping():
    """Domain role aliases and root-relative paths resolve to inventory locations."""
    xref = addnodes.pending_xref(refdomain="py", reftype="meth", reftarget="Client.connect")
    objects: list[extractor.DomainObject] = [
        ("py", "demo.Client.connect", "connect", "method", "api", "demo.Client.connect", 1)
    ]
    assert extractor._xref_target(xref, objects, {("py", "meth"): {"method"}}) == "api#demo.Client.connect"

    any_xref = addnodes.pending_xref(refdomain="", reftype="any", reftarget="demo.Client.connect")
    assert extractor._xref_target(any_xref, objects, {}) == "api#demo.Client.connect"
    assert extractor._reference_target("guide/page", nodes.reference(refuri="/api.html#client")) == (
        "api#client",
        "internal",
    )
