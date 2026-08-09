"""Compile a Sphinx project and extract its documented structure."""

from __future__ import annotations

import posixpath
import subprocess
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from io import StringIO
from os.path import relpath
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urldefrag, urlsplit

from docutils import nodes
from sphinx import __version__ as sphinx_version
from sphinx import addnodes
from sphinx.application import Sphinx
from sphinx.builders.dummy import DummyBuilder
from sphinx.errors import SphinxError
from sphinx.util import logging

from sphinx_lens.lens import DEFAULT_INDEX, INDEX_FILENAME, Entry, IndexMetadata, Lens, LensError, Link

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Set as AbstractSet

    from sphinx.environment import BuildEnvironment
    from sphinx.util.typing import ExtensionMetadata

type DomainObject = tuple[str, str, str, str, str, str, int]

logger = logging.getLogger(__name__)


class BuildError(LensError):
    """Raised when Sphinx cannot produce a Lens index."""


class LensBuilder(DummyBuilder):
    """Sphinx builder that writes a structure-aware Lens index."""

    name = "lens"
    epilog = "The Lens index is in %(outdir)s/index.json."
    allow_parallel = False

    def init(self) -> None:
        """Initialize per-build extraction state."""
        self._entries: list[Entry] = []
        self._links: list[Link] = []
        self._anchor_parents: dict[tuple[str, str], str] = {}
        self._known_locations: set[str] = set()

    def get_target_uri(self, docname: str, typ: str | None = None) -> str:
        """Keep document names in resolved internal reference URIs."""
        return docname

    def prepare_writing(self, docnames: AbstractSet[str]) -> None:
        """Extract entries before Sphinx resolves and writes each doctree."""
        self._entries, self._anchor_parents = _extract_entries(self.env)
        self._known_locations = {entry.location for entry in self._entries}

    def write_doc(self, docname: str, doctree: nodes.document) -> None:
        """Extract links from a doctree resolved by Sphinx."""
        raw_doctree = self.env.get_doctree(docname)
        self._links.extend(_document_links(docname, raw_doctree, doctree, self._anchor_parents, self._known_locations))

    def finish(self) -> None:
        """Extract the completed environment into the builder output directory."""
        self._entries.sort(key=lambda entry: (entry.document, entry.location, entry.kind, entry.ref))
        links = sorted(set(self._links), key=lambda link: (link.source, link.target, link.label))
        source = Path(relpath(self.srcdir, self.outdir)).as_posix()
        lens = Lens(
            source=source,
            entries=self._entries,
            links=links,
            metadata=_index_metadata(self.env, Path(self.srcdir)),
        )
        index_path = lens.write(Path(self.outdir) / INDEX_FILENAME)
        logger.info("wrote Lens index to %s", index_path)


def setup(app: Sphinx) -> ExtensionMetadata:
    """Register the ``lens`` Sphinx builder."""
    app.add_builder(LensBuilder)
    return {"parallel_read_safe": True, "parallel_write_safe": False}


def build(
    source: str | Path,
    output: str | Path | None = None,
    *,
    fail_on_warning: bool = False,
) -> Lens:
    """Compile ``source`` and write the builder artifact as a convenience API."""
    source_path = Path(source).resolve()
    output_dir = Path(output).resolve() if output is not None else source_path / DEFAULT_INDEX.parent
    status = StringIO()
    warnings = StringIO()
    try:
        app = Sphinx(
            srcdir=source_path,
            confdir=source_path,
            outdir=output_dir,
            doctreedir=source_path / "_build" / ".doctrees",
            buildername="lens",
            status=status,
            warning=warnings,
            freshenv=False,
            warningiserror=fail_on_warning,
            exception_on_warning=False,
        )
        app.build(force_all=False)
    except SphinxError as error:
        message = warnings.getvalue().strip() or str(error)
        raise BuildError(message) from error
    if app.statuscode:
        message = warnings.getvalue().strip() or status.getvalue().strip()
        raise BuildError(message)
    lens = Lens.open(output_dir)
    lens.warning_count = app._warncount
    return lens


def _index_metadata(environment: BuildEnvironment, source: Path) -> IndexMetadata:
    documents = {
        Path(source_path).relative_to(source).as_posix(): sha256(Path(source_path).read_bytes()).hexdigest()
        for docname in sorted(environment.found_docs)
        if (source_path := environment.doc2path(docname, base=True))
    }
    return IndexMetadata(
        sphinx_version=sphinx_version,
        extensions=tuple(environment.config.extensions),
        built_at=datetime.now(UTC).isoformat(),
        git_commit=_git_commit(source),
        documents=documents,
    )


def _git_commit(source: Path) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", source, "rev-parse", "HEAD"],  # noqa: S607
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _extract_entries(
    environment: BuildEnvironment,
) -> tuple[list[Entry], dict[tuple[str, str], str]]:
    entries: list[Entry] = []
    anchor_parents: dict[tuple[str, str], str] = {}
    anchor_texts: dict[tuple[str, str], str] = {}
    domain_objects = [
        (domain_name, name, display_name, object_type, docname, anchor, priority)
        for domain_name, domain in sorted(environment.domains.items())
        for name, display_name, object_type, docname, anchor, priority in domain.get_objects()
    ]

    for docname in sorted(environment.found_docs):
        doctree = environment.get_doctree(docname)
        entries.extend(_document_entries(environment, docname, doctree, anchor_parents, anchor_texts))

    objects = list(_domain_entries(domain_objects, entries, anchor_parents, anchor_texts))
    entries.extend(_nest_objects(objects))
    return entries, anchor_parents


def _document_entries(
    environment: BuildEnvironment,
    docname: str,
    doctree: nodes.document,
    anchor_parents: dict[tuple[str, str], str],
    anchor_texts: dict[tuple[str, str], str],
) -> list[Entry]:
    title_node = environment.titles.get(docname)
    title = title_node.astext() if title_node is not None else docname
    entries = [
        Entry(
            ref=docname,
            kind="document",
            title=title,
            text=_own_text(doctree, nested_types=(nodes.section, addnodes.desc)),
            document=docname,
        )
    ]
    for section in doctree.findall(nodes.section):
        anchor = str(section["ids"][0]) if section.get("ids") else ""
        if not anchor:
            continue
        title_child = next((child for child in section.children if isinstance(child, nodes.title)), None)
        section_title = title_child.astext() if title_child is not None else anchor
        parent_section = _ancestor(section, nodes.section)
        parent_anchor = str(parent_section["ids"][0]) if parent_section is not None else ""
        parent = anchor_parents.get((docname, parent_anchor), docname)
        ref = f"{docname}#{anchor}"
        section_ref = docname if parent_section is None and section_title == title else ref
        if section_ref == ref:
            entries.append(
                Entry(
                    ref=ref,
                    kind="section",
                    title=section_title,
                    text=_own_text(section, nested_types=(nodes.section, addnodes.desc)),
                    document=docname,
                    anchor=anchor,
                    parent=parent,
                )
            )
        for element in section.findall(nodes.Element):
            nested_section = _nearest_section(element)
            if nested_section is not section:
                continue
            for element_id in element.get("ids", ()):
                anchor_parents[(docname, str(element_id))] = section_ref
        anchor_parents[(docname, anchor)] = section_ref
    for element in doctree.findall(nodes.Element):
        for element_id in element.get("ids", ()):
            anchor_texts[(docname, str(element_id))] = _anchor_text(element)
    return entries


def _domain_entries(
    domain_objects: Iterable[DomainObject],
    entries: list[Entry],
    anchor_parents: dict[tuple[str, str], str],
    anchor_texts: dict[tuple[str, str], str],
) -> Iterable[Entry]:
    for domain_name, name, display_name, object_type, docname, anchor, _priority in domain_objects:
        if not docname or not anchor:
            continue
        parent = anchor_parents.get((docname, anchor), docname)
        ref = f"{domain_name}:{object_type}:{name}"
        yield Entry(
            ref=ref,
            kind="object",
            title=display_name or name,
            text=anchor_texts.get((docname, anchor), ""),
            document=docname,
            anchor=anchor,
            parent=parent,
            domain=domain_name,
            object_type=object_type,
            name=name,
        )


def _nest_objects(objects: list[Entry]) -> list[Entry]:
    by_name = {(entry.domain, entry.name): entry for entry in objects if entry.name}
    nested: list[Entry] = []
    for entry in objects:
        name_parts = entry.name.split(".") if entry.name else []
        parent = next(
            (
                by_name[(entry.domain, ".".join(name_parts[:end]))]
                for end in range(len(name_parts) - 1, 0, -1)
                if (entry.domain, ".".join(name_parts[:end])) in by_name
            ),
            None,
        )
        nested.append(replace(entry, parent=parent.ref) if parent is not None else entry)
    return nested


def _document_links(
    docname: str,
    raw_doctree: nodes.document,
    resolved_doctree: nodes.document,
    anchor_parents: dict[tuple[str, str], str],
    known_locations: set[str],
) -> Iterable[Link]:
    resolved_links = list(_resolved_links(docname, resolved_doctree, anchor_parents, known_locations))
    resolved_xrefs: Counter[tuple[str, str]] = Counter()
    for link in resolved_links:
        resolved_xrefs[(link.source, link.label)] += 1
        yield link
    yield from _unresolved_xrefs(docname, raw_doctree, anchor_parents, known_locations, resolved_xrefs)
    for toctree in raw_doctree.findall(addnodes.toctree):
        source = _link_source(docname, toctree, anchor_parents)
        for title, target_doc in toctree.get("entries", ()):
            if target_doc == "self" or "://" in target_doc:
                continue
            yield Link(source=source, target=target_doc, label=title or target_doc, kind="internal")


def _resolved_links(
    docname: str,
    doctree: nodes.document,
    anchor_parents: dict[tuple[str, str], str],
    known_locations: set[str],
) -> Iterable[Link]:
    for reference in doctree.findall(nodes.reference):
        if "anchorname" in reference:
            continue
        target, kind = _reference_target(docname, reference)
        if not target:
            continue
        source = _link_source(docname, reference, anchor_parents)
        if kind == "internal" and target not in known_locations:
            target_doc, _separator, _anchor = target.partition("#")
            if target_doc not in known_locations:
                kind = "unresolved"
        label = reference.astext()
        yield Link(source=source, target=target, label=label, kind=kind)


def _unresolved_xrefs(
    docname: str,
    doctree: nodes.document,
    anchor_parents: dict[tuple[str, str], str],
    known_locations: set[str],
    resolved_xrefs: Counter[tuple[str, str]],
) -> Iterable[Link]:
    for xref in doctree.findall(addnodes.pending_xref):
        source = _link_source(docname, xref, anchor_parents)
        key = (source, xref.astext())
        if resolved_xrefs[key]:
            resolved_xrefs[key] -= 1
            continue
        target = str(xref.get("reftarget", ""))
        kind = "internal" if target in known_locations else "unresolved"
        yield Link(source=source, target=target, label=xref.astext(), kind=kind)


def _link_source(
    docname: str,
    node: nodes.Node,
    anchor_parents: dict[tuple[str, str], str],
) -> str:
    description = _ancestor(node, addnodes.desc)
    if description is not None:
        signature = next(description.findall(addnodes.desc_signature), None)
        if signature is not None and signature.get("ids"):
            return f"{docname}#{signature['ids'][0]}"
    section = _nearest_section(node)
    section_anchor = str(section["ids"][0]) if section is not None and section.get("ids") else ""
    return anchor_parents.get((docname, section_anchor), docname)


def _reference_target(docname: str, reference: nodes.reference) -> tuple[str, str]:
    refid = str(reference.get("refid", ""))
    if refid:
        return f"{docname}#{refid}", "internal"
    refuri = str(reference.get("refuri", ""))
    if not refuri:
        return "", "unresolved"
    parsed = urlsplit(refuri)
    if parsed.scheme or parsed.netloc:
        return refuri, "external"
    path, anchor = urldefrag(refuri)
    root_relative = path.startswith("/")
    path = path.lstrip("/")
    target_doc = (
        posixpath.normpath(path if root_relative else posixpath.join(posixpath.dirname(docname), path))
        if path
        else docname
    )
    if target_doc.endswith(".html"):
        target_doc = target_doc.removesuffix(".html")
    return (f"{target_doc}#{anchor}" if anchor else target_doc), "internal"


def _anchor_text(element: nodes.Element) -> str:
    description = _ancestor(element, addnodes.desc)
    if description is not None:
        return _own_text(description, nested_types=(addnodes.desc,))
    item = _ancestor(element, nodes.definition_list_item)
    if item is not None:
        return item.astext().strip()
    if isinstance(element, nodes.section):
        return _own_text(element, nested_types=(nodes.section, addnodes.desc))
    if isinstance(element, nodes.target) and element.parent is not None:
        siblings = element.parent.children
        position = siblings.index(element)
        if position + 1 < len(siblings):
            return siblings[position + 1].astext().strip()
    return element.astext().strip()


def _own_text(element: nodes.Element, *, nested_types: tuple[type[nodes.Element], ...]) -> str:
    clone = element.deepcopy()
    for nested_type in nested_types:
        for nested in list(clone.findall(nested_type)):
            if nested is not clone and nested.parent is not None:
                nested.parent.remove(nested)
    return clone.astext().strip()


def _nearest_section(node: nodes.Node) -> nodes.section | None:
    if isinstance(node, nodes.section):
        return node
    return _ancestor(node, nodes.section)


def _ancestor[NodeType: nodes.Node](node: nodes.Node, node_type: type[NodeType]) -> NodeType | None:
    parent = node.parent
    while parent is not None:
        if isinstance(parent, node_type):
            return parent
        parent = parent.parent
    return None
