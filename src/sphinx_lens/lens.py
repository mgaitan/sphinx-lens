"""Query the semantic index produced from a Sphinx project."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Self

INDEX_VERSION = 1
DEFAULT_INDEX = Path(".sphinx-lens/index.json")


class LensError(Exception):
    """Base error raised for invalid Lens operations."""


class TargetNotFoundError(LensError):
    """Raised when a semantic target cannot be resolved."""


@dataclass(frozen=True, slots=True)
class Entry:
    """A document, section, or domain object in a Sphinx project."""

    ref: str
    kind: str
    title: str
    text: str
    document: str
    anchor: str = ""
    parent: str | None = None
    domain: str | None = None
    object_type: str | None = None
    name: str | None = None

    @property
    def location(self) -> str:
        """Return the physical document location for this entry."""
        return f"{self.document}#{self.anchor}" if self.anchor else self.document


@dataclass(frozen=True, slots=True)
class Link:
    """A directed reference between semantic locations."""

    source: str
    target: str
    label: str
    kind: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A ranked text match in the index."""

    entry: Entry
    score: float
    excerpt: str


@dataclass(frozen=True, slots=True)
class LinkSet:
    """Incoming and outgoing links for a semantic entry."""

    incoming: tuple[Link, ...]
    outgoing: tuple[Link, ...]


class Lens:
    """A portable, read-only view of compiled Sphinx semantics."""

    def __init__(
        self,
        *,
        source: str,
        entries: list[Entry],
        links: list[Link],
        index_path: Path | None = None,
    ) -> None:
        """Create a Lens from already extracted entries and links."""
        self.source = source
        self.entries = tuple(entries)
        self.links = tuple(links)
        self.index_path = index_path
        self._by_ref = {entry.ref: entry for entry in entries}

    @classmethod
    def open(cls, path: str | Path = ".") -> Self:
        """Load an index file or discover it below a project directory."""
        index_path = Path(path)
        if index_path.is_dir():
            direct_index = index_path / "index.json"
            index_path = direct_index if direct_index.exists() else index_path / DEFAULT_INDEX
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            msg = f"Lens index not found: {index_path}"
            raise LensError(msg) from error
        if payload.get("version") != INDEX_VERSION:
            msg = f"Unsupported Lens index version: {payload.get('version')!r}"
            raise LensError(msg)
        return cls(
            source=payload["source"],
            entries=[Entry(**entry) for entry in payload["entries"]],
            links=[Link(**link) for link in payload["links"]],
            index_path=index_path,
        )

    def write(self, path: str | Path) -> Path:
        """Serialize this Lens as deterministic JSON."""
        index_path = Path(path)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "version": INDEX_VERSION,
            "source": self.source,
            "entries": [asdict(entry) for entry in self.entries],
            "links": [asdict(link) for link in self.links],
        }
        index_path.write_text(f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8")
        self.index_path = index_path
        return index_path

    def resolve(self, target: str, name: str | None = None) -> Entry:
        """Resolve a location, object name, or ``(object type, name)`` pair."""
        if name is not None:
            matches = [
                entry
                for entry in self.entries
                if entry.kind == "object" and f"{entry.domain}:{entry.object_type}" == target and entry.name == name
            ]
        else:
            exact = self._by_ref.get(target)
            if exact is not None:
                return exact
            matches = [entry for entry in self.entries if entry.kind == "object" and entry.name == target]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            refs = ", ".join(entry.ref for entry in matches[:5])
            msg = f"Ambiguous target {name or target!r}: {refs}"
            raise LensError(msg)
        raise TargetNotFoundError(name or target)

    def locate(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        """Rank entries by their title, canonical name, and body text."""
        needle = " ".join(query.casefold().split())
        if not needle:
            return []
        words = needle.split()
        results: list[SearchResult] = []
        for entry in self.entries:
            heading = " ".join(filter(None, (entry.ref, entry.title, entry.name))).casefold()
            body = " ".join(entry.text.casefold().split())
            if needle not in heading and needle not in body and not all(word in f"{heading} {body}" for word in words):
                continue
            exact = needle in {entry.ref.casefold(), entry.title.casefold(), (entry.name or "").casefold()}
            score = self._search_score(needle, heading, body, exact=exact)
            results.append(SearchResult(entry=entry, score=score, excerpt=self._excerpt(entry.text, needle)))
        results.sort(key=lambda result: (-result.score, result.entry.ref))
        return results[:limit]

    def inspect(self, target: str) -> Entry:
        """Return structured metadata for a semantic target."""
        return self.resolve(target)

    def read(self, target: str) -> str:
        """Return the normalized text below a semantic target."""
        return self.resolve(target).text

    def children(self, target: str) -> tuple[Entry, ...]:
        """Return direct semantic children of a target."""
        entry = self.resolve(target)
        return tuple(child for child in self.entries if child.parent == entry.ref)

    def references(self, target: str) -> tuple[Link, ...]:
        """Return references originating below a semantic target."""
        entry = self.resolve(target)
        locations = {entry.location, *(child.location for child in self._descendants(entry.ref))}
        return tuple(link for link in self.links if link.source in locations)

    def linked(self, target: str) -> LinkSet:
        """Return incoming and outgoing references for a target."""
        entry = self.resolve(target)
        outgoing = self.references(target)
        incoming = tuple(link for link in self.links if link.target == entry.location)
        return LinkSet(incoming=incoming, outgoing=outgoing)

    def _descendants(self, parent: str) -> list[Entry]:
        children = [entry for entry in self.entries if entry.parent == parent]
        return children + [descendant for child in children for descendant in self._descendants(child.ref)]

    @staticmethod
    def _search_score(needle: str, heading: str, body: str, *, exact: bool) -> float:
        if exact:
            return 1.0
        if needle in heading:
            return 0.9
        if needle in body:
            return 0.7
        return 0.4 + 0.2 * SequenceMatcher(None, needle, heading).ratio()

    @staticmethod
    def _excerpt(text: str, needle: str, *, width: int = 180) -> str:
        normalized = " ".join(text.split())
        position = normalized.casefold().find(needle)
        position = max(position, 0)
        start = max(0, position - width // 3)
        excerpt = normalized[start : start + width]
        if start:
            excerpt = f"...{excerpt}"
        if start + width < len(normalized):
            excerpt = f"{excerpt}..."
        return excerpt
