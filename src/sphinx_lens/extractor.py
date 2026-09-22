"""Compile a Sphinx project and extract its documented structure."""

from __future__ import annotations

import json
import posixpath
import subprocess
import warnings
from dataclasses import dataclass, field, replace
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
from sphinx.util.matching import Matcher

from sphinx_lens.lens import (
    DEFAULT_INDEX,
    INDEX_FILENAME,
    LEGACY_JSON_FILENAME,
    Anchor,
    DocumentInfo,
    Entry,
    IndexMetadata,
    Lens,
    LensError,
    Link,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Set as AbstractSet

    from sphinx.environment import BuildEnvironment
    from sphinx.util.typing import ExtensionMetadata

type DomainObject = tuple[str, str, str, str, str, str, int]


@dataclass(slots=True)
class AnchorIndex:
    """What each ``(document, anchor)`` pair resolves to while extracting.

    ``parents`` gives the entry an anchor belongs to, ``texts`` the prose it
    introduces, and ``order`` its position in the doctree, which is what lets
    `read` compose a scope in source order rather than alphabetically.
    """

    parents: dict[tuple[str, str], str] = field(default_factory=dict)
    texts: dict[tuple[str, str], str] = field(default_factory=dict)
    order: dict[tuple[str, str], int] = field(default_factory=dict)


logger = logging.getLogger(__name__)


class BuildError(LensError):
    """Raised when Sphinx cannot produce a Lens index."""


class LensBuilder(DummyBuilder):
    """Sphinx builder that writes a structure-aware Lens index."""

    name = "lens"
    epilog = f"The Lens index is in %(outdir)s/{INDEX_FILENAME}."
    allow_parallel = False

    def init(self) -> None:
        """Initialize per-build extraction state and listen for failed references."""
        self._entries: list[Entry] = []
        self._links: list[Link] = []
        self._anchors = AnchorIndex()
        self._known_locations: set[str] = set()
        self._no_search: set[str] = set()
        self._document_entries: list[Entry] = []
        self._object_entries: list[Entry] = []
        self._changed_documents: set[str] = set()
        self._incremental = False
        self._skip_write = False
        # Run after resolvers such as intersphinx, so only genuine failures arrive.
        self.events.connect("missing-reference", self._record_missing_reference, priority=1000)

    def get_outdated_docs(self) -> set[str]:
        """Return source-hash changes unless the artifact needs a clean rebuild."""
        index_path = Path(self.outdir) / INDEX_FILENAME
        if not Lens.supports_incremental(index_path, _build_fingerprint(self.env)):
            return self.env.found_docs
        changed = Lens.changed_document_names(index_path, _document_hashes(self.env, Path(self.srcdir)))
        writable = changed & self.env.found_docs
        if writable or not changed:
            return writable
        return {self.env.config.root_doc}

    def get_target_uri(self, docname: str, typ: str | None = None) -> str:
        """Keep document names in resolved internal reference URIs."""
        return docname

    def prepare_writing(self, docnames: AbstractSet[str]) -> None:
        """Extract changed scopes, or the complete model when no prior artifact is compatible."""
        self._no_search = _no_search_documents(self.env)
        index_path = Path(self.outdir) / INDEX_FILENAME
        fingerprint = _build_fingerprint(self.env)
        if not Lens.supports_incremental(index_path, fingerprint):
            self._entries, self._anchors, self._links = _extract_entries(self.env)
            self._known_locations = {entry.location for entry in self._entries}
            return

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            previous = Lens.open(index_path)
        self._changed_documents = set(docnames) | _changed_documents(previous, self.env, Path(self.srcdir))
        self._links = [link for link in self._links if link.source.partition("#")[0] in self._changed_documents]
        if not self._changed_documents:
            self._skip_write = True
            return
        self._incremental = True
        persisted_anchors = Lens.load_anchors(index_path)
        self._anchors = _anchor_index(persisted_anchors, self._changed_documents)
        for docname in sorted(self._changed_documents & self.env.found_docs):
            doctree = self.env.get_doctree(docname)
            self._document_entries.extend(_document_entries(self.env, docname, doctree, self._anchors))
        previous_entries = [
            entry
            for entry in previous.entries
            if entry.document not in self._changed_documents and entry.kind != "object"
        ]
        self._known_locations = {entry.location for entry in [*previous_entries, *self._document_entries]}
        for docname in sorted(self._changed_documents & self.env.found_docs):
            self._links.extend(
                _toctree_links(docname, self.env.get_doctree(docname), self._anchors, self._known_locations)
            )
        domain_objects = [
            (domain_name, name, display_name, object_type, docname, anchor, priority)
            for domain_name, domain in sorted(self.env.domains.items())
            for name, display_name, object_type, docname, anchor, priority in domain.get_objects()
        ]
        self._object_entries = _nest_objects(list(_domain_entries(domain_objects, self._anchors)))

    def write_doc(self, docname: str, doctree: nodes.document) -> None:
        """Collect the references Sphinx resolved while writing this doctree."""
        self._links.extend(_resolved_links(docname, doctree, self._anchors, self._known_locations))

    def _record_missing_reference(
        self,
        app: Sphinx,
        env: BuildEnvironment,
        node: addnodes.pending_xref,
        contnode: nodes.Element,
    ) -> None:
        """Record a cross-reference that no resolver could place."""
        docname = str(node.get("refdoc", ""))
        target = str(node.get("reftarget", ""))
        self._links.append(
            Link(
                source=_link_source(docname, node, self._anchors),
                target=target,
                label=node.astext(),
                kind="internal" if target in self._known_locations else "unresolved",
            )
        )

    def finish(self) -> None:
        """Publish a complete replacement artifact after a full or scoped update."""
        if self._skip_write:
            logger.info("Lens index is up to date")
            return
        source = Path(self.srcdir)
        output = Path(self.outdir)
        metadata = _index_metadata(self.env, source)
        document_hashes = _document_hashes(self.env, source)
        documents = _document_records(self.env)
        if self._incremental:
            entries = [*self._document_entries, *self._object_entries]
            lens = Lens(
                source=_relative_source(source, output),
                entries=entries,
                links=self._links,
                metadata=metadata,
                no_search=self._no_search,
                documents=documents,
                document_hashes=document_hashes,
                anchors=_anchor_records(self._anchors),
            )
            index_path = lens.write_incremental(
                output / INDEX_FILENAME,
                changed_documents=self._changed_documents,
                document_entries=self._document_entries,
                objects=self._object_entries,
                links=self._links,
                known_locations=self._known_locations,
            )
        else:
            self._entries.sort(key=lambda entry: (entry.document, entry.location, entry.kind, entry.ref))
            links = sorted(set(self._links), key=lambda link: (link.source, link.target, link.label))
            lens = Lens(
                source=_relative_source(source, output),
                entries=self._entries,
                links=links,
                metadata=metadata,
                no_search=self._no_search,
                documents=documents,
                document_hashes=document_hashes,
                anchors=_anchor_records(self._anchors),
            )
            index_path = lens.write(output / INDEX_FILENAME)
        (output / LEGACY_JSON_FILENAME).unlink(missing_ok=True)
        logger.info("wrote Lens index to %s", index_path)


def setup(app: Sphinx) -> ExtensionMetadata:
    """Register the `lens` Sphinx builder and its configuration values."""
    app.add_builder(LensBuilder)
    app.add_config_value(
        "lens_no_search",
        [],
        "env",
        types=list,
    )
    return {"parallel_read_safe": True, "parallel_write_safe": False}


def build(
    source: str | Path,
    output: str | Path | None = None,
    *,
    fail_on_warning: bool = False,
    conf_dir: str | Path | None = None,
    doctree_dir: str | Path | None = None,
) -> Lens:
    """Compile ``source`` and write the builder artifact as a convenience API."""
    source_path = Path(source).resolve()
    output_dir = Path(output).resolve() if output is not None else source_path / DEFAULT_INDEX.parent
    conf_path = Path(conf_dir).resolve() if conf_dir is not None else source_path
    doctree_path = Path(doctree_dir).resolve() if doctree_dir is not None else source_path / "_build" / ".doctrees"
    status = StringIO()
    warnings = StringIO()
    try:
        app = Sphinx(
            srcdir=source_path,
            confdir=conf_path,
            outdir=output_dir,
            doctreedir=doctree_path,
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


def _relative_source(source: Path, output: Path) -> str | None:
    """Return ``source`` relative to ``output``, or ``None`` when the two are unrelated.

    A build that writes inside its own source tree — the usual
    `docs/_build/lens` — yields a path that survives moving or cloning the
    project. A build that writes somewhere else entirely would only yield the
    absolute layout of the machine that produced it, which is worth less than
    recording nothing.
    """
    if source not in output.parents and output not in source.parents:
        return None
    return Path(relpath(source, output)).as_posix()


def _no_search_documents(environment: BuildEnvironment) -> set[str]:
    """Return documents excluded from search by metadata or configuration."""
    matcher = Matcher(environment.config.lens_no_search)
    return {
        docname
        for docname in environment.found_docs
        if "no-search" in environment.metadata.get(docname, {})
        or "nosearch" in environment.metadata.get(docname, {})
        or matcher(str(environment.doc2path(docname, base=False)))
    }


def _document_records(environment: BuildEnvironment) -> dict[str, DocumentInfo]:
    """Return each document's title and Sphinx metadata for the index."""
    return {
        docname: DocumentInfo(
            title=environment.titles[docname].astext() if docname in environment.titles else docname,
            metadata=dict(environment.metadata.get(docname, {})),
        )
        for docname in sorted(environment.found_docs)
    }


def _document_hashes(environment: BuildEnvironment, source: Path) -> dict[str, str]:
    """Return each current document's source hash by Sphinx document name."""
    return {
        docname: sha256(Path(source_path).read_bytes()).hexdigest()
        for docname in sorted(environment.found_docs)
        if (source_path := environment.doc2path(docname, base=True)) and Path(source_path).is_file()
    }


def _build_fingerprint(environment: BuildEnvironment) -> str:
    """Hash Lens settings whose changes require a complete extracted model."""
    settings = {
        "extensions": list(environment.config.extensions),
        "language": str(environment.config.language),
        "lens_no_search": list(environment.config.lens_no_search),
        "sphinx_version": sphinx_version,
    }
    return sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def _changed_documents(previous: Lens, environment: BuildEnvironment, source: Path) -> set[str]:
    """Return added, removed, and source-modified documents since the prior artifact."""
    current_hashes = _document_hashes(environment, source)
    return {
        docname
        for docname in set(previous.document_hashes) | set(current_hashes)
        if previous.document_hashes.get(docname) != current_hashes.get(docname)
    }


def _anchor_index(anchors: list[Anchor], changed_documents: set[str]) -> AnchorIndex:
    """Restore unchanged anchors so changed doctrees resolve against the full corpus."""
    unchanged = [anchor for anchor in anchors if anchor.document not in changed_documents]
    return AnchorIndex(
        parents={(anchor.document, anchor.anchor): anchor.parent for anchor in unchanged},
        texts={(anchor.document, anchor.anchor): anchor.text for anchor in unchanged},
        order={(anchor.document, anchor.anchor): anchor.order for anchor in unchanged},
    )


def _anchor_records(anchors: AnchorIndex) -> list[Anchor]:
    """Persist every extracted anchor with the document scope that owns it."""
    return [
        Anchor(
            document=docname,
            anchor=anchor,
            parent=anchors.parents.get((docname, anchor), docname),
            text=anchors.texts.get((docname, anchor), ""),
            order=order,
        )
        for (docname, anchor), order in sorted(anchors.order.items())
    ]


def _index_metadata(environment: BuildEnvironment, source: Path) -> IndexMetadata:
    documents = {
        Path(source_path).relative_to(source).as_posix(): source_hash
        for docname, source_hash in _document_hashes(environment, source).items()
        if (source_path := environment.doc2path(docname, base=True))
    }
    return IndexMetadata(
        sphinx_version=sphinx_version,
        extensions=tuple(environment.config.extensions),
        built_at=datetime.now(UTC).isoformat(),
        git_commit=_git_commit(source),
        documents=documents,
        language=str(environment.config.language),
        build_fingerprint=_build_fingerprint(environment),
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
) -> tuple[list[Entry], AnchorIndex, list[Link]]:
    """Read every doctree once, returning entries, the anchor index, and toctree edges."""
    entries: list[Entry] = []
    links: list[Link] = []
    anchors = AnchorIndex()
    domain_objects = [
        (domain_name, name, display_name, object_type, docname, anchor, priority)
        for domain_name, domain in sorted(environment.domains.items())
        for name, display_name, object_type, docname, anchor, priority in domain.get_objects()
    ]

    doctrees = {docname: environment.get_doctree(docname) for docname in sorted(environment.found_docs)}
    for docname, doctree in doctrees.items():
        entries.extend(_document_entries(environment, docname, doctree, anchors))

    known_locations = {entry.location for entry in entries}
    for docname, doctree in doctrees.items():
        links.extend(_toctree_links(docname, doctree, anchors, known_locations))

    objects = list(_domain_entries(domain_objects, anchors))
    entries.extend(_nest_objects(objects))
    return entries, anchors, links


def _document_entries(
    environment: BuildEnvironment,
    docname: str,
    doctree: nodes.document,
    anchors: AnchorIndex,
) -> list[Entry]:
    for position, element in enumerate(doctree.findall(nodes.Element)):
        for element_id in element.get("ids", ()):
            anchors.texts[(docname, str(element_id))] = _anchor_text(element)
            anchors.order[(docname, str(element_id))] = position
    title_node = environment.titles.get(docname)
    title = title_node.astext() if title_node is not None else docname
    document_text = _own_text(doctree, nested_types=(nodes.section, addnodes.desc))
    sections: list[Entry] = []
    for section in doctree.findall(nodes.section):
        anchor = str(section["ids"][0]) if section.get("ids") else ""
        if not anchor:
            continue
        title_child = next((child for child in section.children if isinstance(child, nodes.title)), None)
        section_title = title_child.astext() if title_child is not None else anchor
        parent_section = _ancestor(section, nodes.section)
        parent_anchor = str(parent_section["ids"][0]) if parent_section is not None else ""
        parent = anchors.parents.get((docname, parent_anchor), docname)
        ref = f"{docname}#{anchor}"
        section_ref = docname if parent_section is None and section_title == title else ref
        section_text = _own_text(section, nested_types=(nodes.section, addnodes.desc))
        if section_ref == ref:
            sections.append(
                Entry(
                    ref=ref,
                    kind="section",
                    title=section_title,
                    text=section_text,
                    document=docname,
                    anchor=anchor,
                    order=anchors.order.get((docname, anchor), 0),
                    parent=parent,
                )
            )
        else:
            # Sphinx titles a document from its lone top-level section, and that
            # section is addressed as the document itself. Its prose belongs to
            # the document entry, which would otherwise hold nothing at all.
            document_text = "\n\n".join(filter(None, (document_text, section_text)))
        for element in section.findall(nodes.Element):
            nested_section = _nearest_section(element)
            if nested_section is not section:
                continue
            for element_id in element.get("ids", ()):
                anchors.parents[(docname, str(element_id))] = section_ref
        anchors.parents[(docname, anchor)] = section_ref
    document = Entry(ref=docname, kind="document", title=title, text=document_text, document=docname)
    return [document, *sections]


def _domain_entries(domain_objects: Iterable[DomainObject], anchors: AnchorIndex) -> Iterable[Entry]:
    for domain_name, name, display_name, object_type, docname, anchor, _priority in domain_objects:
        if not docname or not anchor:
            continue
        parent = anchors.parents.get((docname, anchor), docname)
        ref = f"{domain_name}:{object_type}:{name}"
        yield Entry(
            ref=ref,
            kind="object",
            title=display_name or name,
            text=anchors.texts.get((docname, anchor), ""),
            document=docname,
            anchor=anchor,
            order=anchors.order.get((docname, anchor), 0),
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


def _toctree_links(
    docname: str,
    doctree: nodes.document,
    anchors: AnchorIndex,
    known_locations: set[str],
) -> Iterable[Link]:
    """Yield toctree edges and classify missing document targets as unresolved."""
    for toctree in doctree.findall(addnodes.toctree):
        source = _link_source(docname, toctree, anchors)
        for title, target_doc in toctree.get("entries", ()):
            if target_doc == "self" or "://" in target_doc:
                continue
            kind = "internal" if target_doc in known_locations else "unresolved"
            yield Link(source=source, target=target_doc, label=title or target_doc, kind=kind)


def _resolved_links(
    docname: str,
    doctree: nodes.document,
    anchors: AnchorIndex,
    known_locations: set[str],
) -> Iterable[Link]:
    for reference in doctree.findall(nodes.reference):
        if "anchorname" in reference:
            continue
        target, kind = _reference_target(docname, reference)
        if not target:
            continue
        source = _link_source(docname, reference, anchors)
        if kind == "internal" and target not in known_locations:
            target_doc, separator, anchor = target.partition("#")
            if not separator or (target_doc, anchor) not in anchors.order:
                # A reference into a document that exists, at an anchor that does
                # not, is not resolved. Reporting it as internal would hide every
                # stale anchor in a corpus behind a link that appears to work.
                kind = "unresolved"
        label = reference.astext()
        yield Link(source=source, target=target, label=label, kind=kind)


def _link_source(
    docname: str,
    node: nodes.Node,
    anchors: AnchorIndex,
) -> str:
    description = _ancestor(node, addnodes.desc)
    if description is not None:
        signature = next(description.findall(addnodes.desc_signature), None)
        if signature is not None and signature.get("ids"):
            return f"{docname}#{signature['ids'][0]}"
    section = _nearest_section(node)
    section_anchor = str(section["ids"][0]) if section is not None and section.get("ids") else ""
    return anchors.parents.get((docname, section_anchor), docname)


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
    for image in clone.findall(nodes.image):
        alt = str(image.get("alt", ""))
        uri = str(image.get("uri", ""))
        image.replace_self(nodes.Text(f"![{alt}]({uri})"))
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
