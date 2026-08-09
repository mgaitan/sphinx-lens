"""Compile a Sphinx project and extract its semantic structure."""

from __future__ import annotations

import posixpath
from collections import defaultdict
from dataclasses import dataclass, replace
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urldefrag, urlsplit

from docutils import nodes
from sphinx import addnodes
from sphinx.application import Sphinx

from sphinx_lens.lens import DEFAULT_INDEX, Entry, Lens, Link

if TYPE_CHECKING:
    from collections.abc import Iterable

type DomainObject = tuple[str, str, str, str, str, str, int]
type RoleTypes = dict[tuple[str, str], set[str]]


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    """Lookup data needed to classify extracted references."""

    known_locations: set[str]
    domain_objects: list[DomainObject]
    role_types: RoleTypes


def build(source: str | Path, output: str | Path | None = None) -> Lens:
    """Compile ``source`` with Sphinx and write a portable semantic index."""
    source_path = Path(source).resolve()
    output_path = Path(output) if output is not None else source_path / DEFAULT_INDEX
    work_path = output_path.parent
    status = StringIO()
    warnings = StringIO()
    app = Sphinx(
        srcdir=source_path,
        confdir=source_path,
        outdir=work_path / "build",
        doctreedir=work_path / "doctrees",
        buildername="dummy",
        status=status,
        warning=warnings,
        freshenv=True,
        exception_on_warning=False,
    )
    app.build(force_all=True)
    if app.statuscode:
        message = warnings.getvalue().strip() or status.getvalue().strip()
        raise RuntimeError(message)
    lens = _extract(app, source_path)
    lens.write(output_path)
    return lens


def _extract(app: Sphinx, source: Path) -> Lens:
    entries: list[Entry] = []
    links: list[Link] = []
    anchor_parents: dict[tuple[str, str], str] = {}
    anchor_texts: dict[tuple[str, str], str] = {}
    doctrees: dict[str, nodes.document] = {}
    domain_objects = [
        (domain_name, name, display_name, object_type, docname, anchor, priority)
        for domain_name, domain in sorted(app.env.domains.items())
        for name, display_name, object_type, docname, anchor, priority in domain.get_objects()
    ]
    role_types: RoleTypes = defaultdict(set)
    for domain_name, domain in app.env.domains.items():
        for object_type, object_type_definition in domain.object_types.items():
            for role in object_type_definition.roles:
                role_types[(domain_name, role)].add(object_type)

    for docname in sorted(app.env.found_docs):
        doctree = app.env.get_doctree(docname)
        doctrees[docname] = doctree
        entries.extend(_document_entries(app, docname, doctree, anchor_parents, anchor_texts))

    objects = list(_domain_entries(domain_objects, entries, anchor_parents, anchor_texts))
    objects = _nest_objects(objects)
    entries.extend(objects)
    resolution = ResolutionContext(
        known_locations={entry.location for entry in entries},
        domain_objects=domain_objects,
        role_types=role_types,
    )
    for docname, doctree in doctrees.items():
        links.extend(_document_links(docname, doctree, anchor_parents, resolution))

    entries.sort(key=lambda entry: (entry.document, entry.location, entry.kind, entry.ref))
    links = sorted(set(links), key=lambda link: (link.source, link.target, link.label))
    return Lens(source=str(source), entries=entries, links=links)


def _document_entries(
    app: Sphinx,
    docname: str,
    doctree: nodes.document,
    anchor_parents: dict[tuple[str, str], str],
    anchor_texts: dict[tuple[str, str], str],
) -> list[Entry]:
    title_node = app.env.titles.get(docname)
    title = title_node.astext() if title_node is not None else docname
    entries = [Entry(ref=docname, kind="document", title=title, text=doctree.astext(), document=docname)]
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
                    text=section.astext(),
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
    for signature in doctree.findall(addnodes.desc_signature):
        description = _ancestor(signature, addnodes.desc)
        for signature_id in signature.get("ids", ()):
            anchor_texts[(docname, str(signature_id))] = (description or signature).astext()
    return entries


def _domain_entries(
    domain_objects: Iterable[DomainObject],
    entries: list[Entry],
    anchor_parents: dict[tuple[str, str], str],
    anchor_texts: dict[tuple[str, str], str],
) -> Iterable[Entry]:
    text_by_ref = {entry.ref: entry.text for entry in entries}
    for domain_name, name, display_name, object_type, docname, anchor, _priority in domain_objects:
        if not docname or not anchor:
            continue
        parent = anchor_parents.get((docname, anchor), docname)
        ref = f"{domain_name}:{object_type}:{name}"
        yield Entry(
            ref=ref,
            kind="object",
            title=display_name or name,
            text=anchor_texts.get((docname, anchor), text_by_ref.get(parent, "")),
            document=docname,
            anchor=anchor,
            parent=parent,
            domain=domain_name,
            object_type=object_type,
            name=name,
        )


def _nest_objects(objects: list[Entry]) -> list[Entry]:
    nested: list[Entry] = []
    for entry in objects:
        parents = [
            candidate
            for candidate in objects
            if candidate.domain == entry.domain
            and candidate.name
            and entry.name
            and entry.name.startswith(f"{candidate.name}.")
        ]
        parent = max(parents, key=lambda candidate: len(candidate.name or ""), default=None)
        nested.append(replace(entry, parent=parent.ref) if parent is not None else entry)
    return nested


def _document_links(
    docname: str,
    doctree: nodes.document,
    anchor_parents: dict[tuple[str, str], str],
    resolution: ResolutionContext,
) -> Iterable[Link]:
    for xref in doctree.findall(addnodes.pending_xref):
        target = _xref_target(xref, resolution.domain_objects, resolution.role_types)
        source = _link_source(docname, xref, anchor_parents)
        yield Link(
            source=source,
            target=target or str(xref.get("reftarget", "")),
            label=xref.astext(),
            kind="internal" if target else "unresolved",
        )
    for reference in doctree.findall(nodes.reference):
        target, kind = _reference_target(docname, reference)
        if not target:
            continue
        source = _link_source(docname, reference, anchor_parents)
        if kind == "internal" and target not in resolution.known_locations:
            target_doc, _separator, _anchor = target.partition("#")
            if target_doc not in resolution.known_locations:
                kind = "unresolved"
        yield Link(source=source, target=target, label=reference.astext(), kind=kind)
    for toctree in doctree.findall(addnodes.toctree):
        source = _link_source(docname, toctree, anchor_parents)
        for title, target_doc in toctree.get("entries", ()):
            if target_doc == "self" or "://" in target_doc:
                continue
            yield Link(source=source, target=target_doc, label=title or target_doc, kind="internal")


def _xref_target(
    xref: addnodes.pending_xref,
    domain_objects: list[DomainObject],
    role_types: RoleTypes,
) -> str:
    domain = str(xref.get("refdomain", ""))
    role = str(xref.get("reftype", ""))
    object_types = role_types.get((domain, role), {role})
    target = str(xref.get("reftarget", ""))
    candidates = [
        item
        for item in domain_objects
        if (not domain or item[0] == domain)
        and (role == "any" or item[3] in object_types)
        and (item[1] == target or item[1].endswith(f".{target}"))
    ]
    if len(candidates) != 1:
        return ""
    _domain, _name, _display_name, _object_type, docname, anchor, _priority = candidates[0]
    return f"{docname}#{anchor}" if anchor else docname


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
