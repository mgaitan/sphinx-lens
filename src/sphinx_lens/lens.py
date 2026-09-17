"""Query the semantic index produced from a Sphinx project."""

from __future__ import annotations

import json
import posixpath
import re
import unicodedata
import warnings
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any, Self, cast

from sphinx.search import SearchLanguage
from sphinx.search import languages as sphinx_languages

INDEX_VERSION = 4
INDEX_FILENAME = "index.json"
DEFAULT_INDEX = Path("_build/lens") / INDEX_FILENAME
LEGACY_INDEX = Path(".sphinx-lens") / INDEX_FILENAME


def _index_candidates(directory: Path) -> list[Path]:
    """Return conventional indexes near a project directory or its parents."""
    candidates: list[Path] = []
    for root in (directory, *directory.parents):
        candidates.extend((root / INDEX_FILENAME, root / DEFAULT_INDEX, root / LEGACY_INDEX))
        candidates.extend(
            conf.parent / DEFAULT_INDEX
            for conf in sorted(root.glob("*/conf.py"))
            if not conf.parent.name.startswith(".")
        )
    return list(dict.fromkeys(candidates))


def _fold_text(text: str) -> str:
    """Casefold text and remove combining marks for accent-insensitive search."""
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _search_language(language: str) -> SearchLanguage | None:
    """Return Sphinx's stemmer for a configured language, when available."""
    language_class = sphinx_languages.get(language) or sphinx_languages.get(language.partition("_")[0])
    if language_class is None:
        return None
    if isinstance(language_class, str):
        module, class_name = language_class.rsplit(".", 1)
        language_class = cast("type[SearchLanguage]", getattr(import_module(module), class_name))
    return language_class({})


def _search_words(text: str, language: SearchLanguage | None) -> set[str]:
    """Return normalized search terms, stemmed when Sphinx supports the language."""
    words = language.split(text) if language is not None else text.split()
    if language is None:
        return set(words)
    return {language.stem(word) for word in words}


def _words_match(words: set[str], heading: str, body: str, language: SearchLanguage | None) -> bool:
    """Check unordered query terms against a folded heading and body."""
    if not words:
        return False
    if language is None:
        return all(word in f"{heading} {body}" for word in words)
    return words <= _search_words(f"{heading} {body}", language)


def _term_coverage(
    words: set[str],
    heading: str,
    body: str,
    language: SearchLanguage | None,
) -> tuple[float, float]:
    """Return the fraction of query terms found in the heading and body."""
    if not words:
        return 0.0, 0.0
    if language is None:
        heading_terms = {word for word in words if word in heading}
        body_terms = {word for word in words if word in body}
    else:
        heading_terms = words & _search_words(heading, language)
        body_terms = words & _search_words(body, language)
    count = len(words)
    return len(heading_terms) / count, len(body_terms) / count


class LensError(Exception):
    """Base error raised for invalid Lens operations."""


class TargetNotFoundError(LensError):
    """Raised when a semantic target cannot be resolved."""


class StaleIndexWarning(UserWarning):
    """Warn that source files no longer match an index."""


@dataclass(frozen=True, slots=True)
class IndexMetadata:
    """Record how and from which sources an index was built."""

    sphinx_version: str = ""
    extensions: tuple[str, ...] = ()
    built_at: str = ""
    git_commit: str | None = None
    documents: dict[str, str] = field(default_factory=dict)
    language: str = ""


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    """Store a document title and the file-wide metadata Sphinx recorded."""

    title: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Entry:
    """A document, section, or domain object in a Sphinx project."""

    ref: str
    kind: str
    title: str
    text: str
    document: str
    anchor: str = ""
    order: int = 0
    parent: str | None = None
    domain: str | None = None
    object_type: str | None = None
    name: str | None = None

    @property
    def location(self) -> str:
        """Return the physical document location for this entry."""
        return f"{self.document}#{self.anchor}" if self.anchor else self.document

    @property
    def sort_key(self) -> tuple[int, str]:
        """Return the key that restores source order among sibling entries."""
        return (self.order, self.ref)


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
    """A portable, read-only view of compiled Sphinx structure."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        source: str | None,
        entries: list[Entry],
        links: list[Link],
        metadata: IndexMetadata | None = None,
        index_path: Path | None = None,
        no_search: set[str] | frozenset[str] = frozenset(),
        documents: dict[str, DocumentInfo] | None = None,
    ) -> None:
        """Create a Lens from already extracted entries and links."""
        self.source = source
        self.entries = tuple(entries)
        self.links = tuple(links)
        self.metadata = metadata or IndexMetadata()
        self.index_path = index_path
        self.no_search = frozenset(no_search)
        self.documents = documents or {}
        self.warning_count = 0
        self._by_ref = {entry.ref: entry for entry in entries}

    @classmethod
    def open(cls, path: str | Path = ".") -> Self:
        """Load an index file or discover it below a project directory."""
        index_path = Path(path)
        if index_path.is_dir():
            candidates = _index_candidates(index_path.resolve())
            index_path = next((candidate for candidate in candidates if candidate.is_file()), candidates[1])
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            msg = f"Lens index not found: {index_path}"
            raise LensError(msg) from error
        if payload.get("version") != INDEX_VERSION:
            msg = (
                f"Unsupported Lens index version: {payload.get('version')!r}; "
                "rebuild the index with the current version"
            )
            raise LensError(msg)
        metadata_payload = payload.get("metadata", {})
        lens = cls(
            source=payload["source"],
            entries=[Entry(**entry) for entry in payload["entries"]],
            links=[Link(**link) for link in payload["links"]],
            metadata=IndexMetadata(
                sphinx_version=metadata_payload.get("sphinx_version", ""),
                extensions=tuple(metadata_payload.get("extensions", ())),
                built_at=metadata_payload.get("built_at", ""),
                git_commit=metadata_payload.get("git_commit"),
                documents=metadata_payload.get("documents", {}),
                language=metadata_payload.get("language", ""),
            ),
            index_path=index_path,
            no_search=payload.get("no_search", ()),
            documents={docname: DocumentInfo(**record) for docname, record in payload.get("documents", {}).items()},
        )
        lens._warn_if_stale()
        return lens

    def write(self, path: str | Path) -> Path:
        """Serialize this Lens as deterministic JSON."""
        index_path = Path(path)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "version": INDEX_VERSION,
            "source": self.source,
            "metadata": asdict(self.metadata),
            "no_search": sorted(self.no_search),
            "documents": {docname: asdict(document) for docname, document in sorted(self.documents.items())},
            "entries": [asdict(entry) for entry in self.entries],
            "links": [asdict(link) for link in self.links],
        }
        index_path.write_text(f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8")
        self.index_path = index_path
        return index_path

    def _warn_if_stale(self) -> None:
        if self.index_path is None or not self.metadata.documents:
            return
        if self.source is None:
            warnings.warn(
                "Lens index staleness cannot be checked because its source is outside the artifact",
                StaleIndexWarning,
                stacklevel=2,
            )
            return
        source_dir = (self.index_path.parent / self.source).resolve()
        if not source_dir.is_dir():
            return
        changed = [
            relative_path
            for relative_path, expected_hash in self.metadata.documents.items()
            if not (path := source_dir / relative_path).is_file()
            or sha256(path.read_bytes()).hexdigest() != expected_hash
        ]
        if changed:
            warnings.warn(
                f"Lens index may be stale; {len(changed)} source file(s) changed",
                StaleIndexWarning,
                stacklevel=2,
            )

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

    def locate(  # noqa: PLR0913
        self,
        query: str,
        *,
        limit: int = 10,
        regex: bool = False,
        kinds: set[str] | None = None,
        domain: str | None = None,
        under: set[str | Path] | None = None,
    ) -> list[SearchResult]:
        """Rank filtered entries using text terms or a regular expression."""
        needle = " ".join(query.casefold().split())
        search_needle = _fold_text(needle)
        if not search_needle:
            return []
        if regex:
            try:
                pattern = re.compile(query, re.IGNORECASE)
            except re.error as error:
                msg = f"Invalid regular expression: {error}"
                raise LensError(msg) from error
        search_language = _search_language(self.metadata.language)
        words = _search_words(search_needle, search_language)
        results: list[SearchResult] = []
        for entry in self.entries:
            if not self._entry_allowed(entry, kinds, domain, under):
                continue
            heading = " ".join(filter(None, (entry.ref, entry.title, entry.name)))
            body = " ".join(entry.text.split())
            if regex:
                result = self._regex_result(entry, pattern, body)
                if result is not None:
                    results.append(result)
                continue
            folded_heading = _fold_text(heading)
            folded_body = _fold_text(body)
            if (
                search_needle not in folded_heading
                and search_needle not in folded_body
                and not _words_match(words, folded_heading, folded_body, search_language)
            ):
                continue
            exact = search_needle in {
                _fold_text(entry.ref),
                _fold_text(entry.title),
                _fold_text(entry.name or ""),
            }
            score = self._search_score(
                search_needle,
                folded_heading,
                folded_body,
                exact=exact,
                coverage=_term_coverage(words, folded_heading, folded_body, search_language),
            )
            results.append(SearchResult(entry=entry, score=score, excerpt=self._excerpt(entry.text, search_needle)))
        results.sort(key=lambda result: (-result.score, result.entry.ref))
        return self._distinct_results(results, limit)

    def _entry_allowed(
        self,
        entry: Entry,
        kinds: set[str] | None,
        domain: str | None,
        under: set[str | Path] | None,
    ) -> bool:
        prefixes = {posixpath.normpath(Path(prefix).as_posix()).strip("/") for prefix in under or ()}
        prefixes.discard(".")
        return (
            entry.document not in self.no_search
            and (
                not prefixes
                or any(entry.document == prefix or entry.document.startswith(f"{prefix}/") for prefix in prefixes)
            )
            and (kinds is None or entry.kind in kinds)
            and (domain is None or entry.domain == domain)
        )

    @staticmethod
    def _distinct_results(results: list[SearchResult], limit: int) -> list[SearchResult]:
        distinct: list[SearchResult] = []
        seen_locations: set[str] = set()
        for result in results:
            if result.entry.location in seen_locations:
                continue
            seen_locations.add(result.entry.location)
            distinct.append(result)
        return distinct[:limit]

    @classmethod
    def _regex_result(
        cls,
        entry: Entry,
        pattern: re.Pattern[str],
        body: str,
    ) -> SearchResult | None:
        heading_match = next(
            (match for value in (entry.ref, entry.title, entry.name or "") if (match := pattern.search(value))),
            None,
        )
        body_match = pattern.search(body)
        if heading_match is None and body_match is None:
            return None
        exact = any(pattern.fullmatch(value) for value in (entry.ref, entry.title, entry.name or ""))
        score = 1.0 if exact else 0.9 if heading_match is not None else 0.7
        matched_text = body_match.group() if body_match is not None else ""
        return SearchResult(entry=entry, score=score, excerpt=cls._excerpt(entry.text, matched_text.casefold()))

    def document_metadata(self, target: str) -> dict[str, Any]:
        """Return Sphinx's file-wide metadata for the document containing ``target``."""
        entry = self.resolve(target)
        document = self.documents.get(entry.document)
        return dict(document.metadata) if document is not None else {}

    def inspect(self, target: str) -> Entry:
        """Return structured metadata for a semantic target."""
        return self.resolve(target)

    def read(self, target: str) -> str:
        """Compose normalized text from a target and its structural descendants."""
        entry = self.resolve(target)
        parts: list[str] = []
        seen: set[tuple[str, str]] = set()
        for descendant in (entry, *self._descendants(entry.ref)):
            key = (descendant.location, descendant.text)
            if descendant.text and key not in seen:
                seen.add(key)
                parts.append(descendant.text)
        return "\n\n".join(parts)

    def children(self, target: str) -> tuple[Entry, ...]:
        """Return direct semantic children of a target, in source order."""
        entry = self.resolve(target)
        return tuple(self._children(entry.ref))

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

    def _children(self, parent: str) -> list[Entry]:
        return sorted((entry for entry in self.entries if entry.parent == parent), key=lambda entry: entry.sort_key)

    def _descendants(self, parent: str) -> list[Entry]:
        """Return every nested entry below ``parent``, depth first in source order."""
        return [nested for child in self._children(parent) for nested in (child, *self._descendants(child.ref))]

    @staticmethod
    def _search_score(
        needle: str,
        heading: str,
        body: str,
        *,
        exact: bool,
        coverage: tuple[float, float] | None = None,
    ) -> float:
        if exact:
            return 1.0
        if needle in heading:
            return 0.9
        if needle in body:
            length_quality = min(1.0, 40 / max(len(body.split()), 1))
            return 0.55 + 0.15 * length_quality
        if coverage is not None:
            heading_coverage, body_coverage = coverage
            term_coverage = max(heading_coverage, body_coverage)
            length_quality = min(1.0, 40 / max(len(body.split()), 1))
            return min(0.69, 0.34 + 0.2 * term_coverage + 0.1 * heading_coverage + 0.1 * length_quality)
        return 0.4 + 0.2 * SequenceMatcher(None, needle, heading).ratio()

    @staticmethod
    def _excerpt(text: str, needle: str, *, width: int = 180) -> str:
        normalized = " ".join(text.split())
        position = normalized.casefold().find(needle)
        if position < 0:
            position = _fold_text(normalized).find(_fold_text(needle))
        position = max(position, 0)
        start = max(0, position - width // 3)
        excerpt = normalized[start : start + width]
        if start:
            excerpt = f"...{excerpt}"
        if start + width < len(normalized):
            excerpt = f"{excerpt}..."
        return excerpt
