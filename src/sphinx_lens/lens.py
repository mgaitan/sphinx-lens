"""Query the semantic index produced from a Sphinx project."""

from __future__ import annotations

import json
import os
import posixpath
import re
import secrets
import sqlite3
import stat
import unicodedata
import warnings
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from shutil import copyfile
from typing import TYPE_CHECKING, Any, Self, cast

from sphinx.search import SearchLanguage
from sphinx.search import languages as sphinx_languages

if TYPE_CHECKING:
    from collections.abc import Iterator

INDEX_VERSION = 6
INDEX_FILENAME = "index.sqlite"
DEFAULT_INDEX = Path("_build/lens") / INDEX_FILENAME
LEGACY_INDEX = Path(".sphinx-lens") / INDEX_FILENAME
LEGACY_JSON_FILENAME = "index.json"
FTS5_TRIGRAM_SIZE = 3

_ENTRY_COLUMNS = "ref, kind, title, text, document, anchor, source_order, parent, domain, object_type, name"
_QUALIFIED_ENTRY_COLUMNS = ", ".join(f"entries.{column.strip()}" for column in _ENTRY_COLUMNS.split(","))
_SELECT_ALL_ENTRIES = f"SELECT {_ENTRY_COLUMNS} FROM entries ORDER BY document, anchor, kind, ref"  # noqa: S608
_SELECT_OBJECT_IDENTITY = (
    f"SELECT {_ENTRY_COLUMNS} FROM entries "  # noqa: S608
    "WHERE kind = 'object' AND domain = ? AND object_type = ? AND name = ?"
)
_SELECT_ENTRY_REF = f"SELECT {_ENTRY_COLUMNS} FROM entries WHERE ref = ?"  # noqa: S608
_SELECT_OBJECT_NAME = f"SELECT {_ENTRY_COLUMNS} FROM entries WHERE kind = 'object' AND name = ? ORDER BY ref LIMIT 6"  # noqa: S608
_SELECT_SEARCHABLE_ENTRIES = f"SELECT {_ENTRY_COLUMNS} FROM entries WHERE searchable = 1 ORDER BY id"  # noqa: S608
_SELECT_FTS_ENTRIES = f"""SELECT {_QUALIFIED_ENTRY_COLUMNS}
    FROM entries_fts JOIN entries ON entries.id = entries_fts.rowid
    WHERE entries_fts MATCH ? AND entries.searchable = 1
    ORDER BY bm25(entries_fts), entries.ref"""  # noqa: S608
_SELECT_TRIGRAM_ENTRIES = f"""SELECT {_QUALIFIED_ENTRY_COLUMNS}
    FROM entries_trigram JOIN entries ON entries.id = entries_trigram.rowid
    WHERE entries_trigram MATCH ? AND entries.searchable = 1
    ORDER BY bm25(entries_trigram), entries.ref"""  # noqa: S608
_SELECT_CHILDREN = f"SELECT {_ENTRY_COLUMNS} FROM entries WHERE parent = ? ORDER BY source_order, ref"  # noqa: S608
_SELECT_DESCENDANTS = f"""WITH RECURSIVE tree AS (
    SELECT {_ENTRY_COLUMNS} FROM entries WHERE parent = ?
    UNION ALL
    SELECT {_QUALIFIED_ENTRY_COLUMNS}
    FROM entries JOIN tree ON entries.parent = tree.ref
)
SELECT {_ENTRY_COLUMNS} FROM tree"""  # noqa: S608

_SCHEMA = """
CREATE TABLE artifact (
    schema_version INTEGER NOT NULL,
    source TEXT,
    sphinx_version TEXT NOT NULL,
    extensions TEXT NOT NULL,
    built_at TEXT NOT NULL,
    git_commit TEXT,
    language TEXT NOT NULL,
    no_search TEXT NOT NULL,
    source_documents TEXT NOT NULL,
    build_fingerprint TEXT NOT NULL
);
CREATE TABLE documents (
    name TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    metadata TEXT NOT NULL,
    source_hash TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE anchors (
    document TEXT NOT NULL,
    anchor TEXT NOT NULL,
    parent TEXT NOT NULL,
    text TEXT NOT NULL,
    source_order INTEGER NOT NULL,
    PRIMARY KEY (document, anchor)
) WITHOUT ROWID;
CREATE INDEX anchors_document_order ON anchors(document, source_order);
CREATE TABLE entries (
    id INTEGER PRIMARY KEY,
    ref TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    document TEXT NOT NULL,
    anchor TEXT NOT NULL,
    source_order INTEGER NOT NULL,
    parent TEXT,
    domain TEXT,
    object_type TEXT,
    name TEXT,
    normalized_ref TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    searchable INTEGER NOT NULL
);
CREATE INDEX entries_document_order ON entries(document, source_order, ref);
CREATE INDEX entries_parent_order ON entries(parent, source_order, ref);
CREATE INDEX entries_object_name ON entries(name) WHERE kind = 'object';
CREATE INDEX entries_object_identity ON entries(domain, object_type, name) WHERE kind = 'object';
CREATE INDEX entries_kind_domain ON entries(kind, domain);
CREATE TABLE links (
    source TEXT NOT NULL,
    source_document TEXT NOT NULL,
    target TEXT NOT NULL,
    label TEXT NOT NULL,
    kind TEXT NOT NULL
);
CREATE INDEX links_source ON links(source);
CREATE INDEX links_source_document ON links(source_document);
CREATE INDEX links_target ON links(target);
CREATE VIRTUAL TABLE entries_fts USING fts5(
    searchable,
    content='',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE entries_trigram USING fts5(
    searchable,
    content='',
    tokenize='trigram'
);
"""


def _sphinx_source_candidates(directory: Path) -> list[Path]:
    """Return Sphinx source directories near a project directory or its parents."""
    for root in (directory, *directory.parents):
        candidates = [root] if (root / "conf.py").is_file() else []
        if root == directory:
            candidates.extend(
                conf.parent for conf in sorted(root.glob("*/conf.py")) if not conf.parent.name.startswith(".")
            )
        if candidates:
            return list(dict.fromkeys(candidates))
    return []


def discover_source(path: str | Path = ".") -> Path:
    """Discover one Sphinx source directory from a repository or nested path."""
    candidates = _sphinx_source_candidates(Path(path).resolve())
    if not candidates:
        msg = f"Sphinx conf.py not found from: {Path(path)}"
        raise LensError(msg)
    if len(candidates) > 1:
        joined = ", ".join(str(candidate) for candidate in candidates)
        msg = f"Multiple Sphinx source directories found; choose one explicitly: {joined}"
        raise LensError(msg)
    return candidates[0]


def _index_candidates(directory: Path) -> list[Path]:
    """Return conventional indexes near a project directory or its parents."""
    candidates: list[Path] = []
    for root in (directory, *directory.parents):
        candidates.extend((root / INDEX_FILENAME, root / DEFAULT_INDEX, root / LEGACY_INDEX))
    candidates.extend(source / DEFAULT_INDEX for source in _sphinx_source_candidates(directory))
    return list(dict.fromkeys(candidates))


def _legacy_json_candidates(directory: Path) -> list[Path]:
    """Return old JSON index locations so callers receive a rebuild error."""
    candidates: list[Path] = []
    for root in (directory, *directory.parents):
        candidates.extend(
            (
                root / LEGACY_JSON_FILENAME,
                root / DEFAULT_INDEX.parent / LEGACY_JSON_FILENAME,
                root / LEGACY_INDEX.parent / LEGACY_JSON_FILENAME,
            )
        )
    candidates.extend(
        source / DEFAULT_INDEX.parent / LEGACY_JSON_FILENAME for source in _sphinx_source_candidates(directory)
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


def _fts_query(text: str, language: SearchLanguage | None) -> str:
    """Build an FTS5 AND query with prefix and language-aware stem alternatives."""
    words = re.findall(r"\w+", text, flags=re.UNICODE) if language is None else language.split(text)
    groups: list[str] = []
    for word in dict.fromkeys(words):
        folded = _fold_text(word)
        alternatives = {folded, language.stem(folded) if language is not None else folded}
        quoted = [f'"{term.replace(chr(34), chr(34) * 2)}"*' for term in sorted(alternatives) if term]
        if quoted:
            groups.append(f"({' OR '.join(quoted)})")
    return " AND ".join(groups)


def _trigram_query(text: str) -> str:
    """Build an FTS5 trigram query from terms long enough to index."""
    terms = dict.fromkeys(re.findall(r"\w+", text, flags=re.UNICODE))
    quoted = [f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms if len(term) >= FTS5_TRIGRAM_SIZE]
    return " AND ".join(quoted)


def _entry_folded_text(entry: Entry) -> str:
    """Return the folded text searched for exact and infix matches."""
    return _fold_text(" ".join(filter(None, (entry.ref, entry.title, entry.name, entry.text))))


def _entry_search_text(entry: Entry, language: SearchLanguage | None) -> str:
    """Return folded source text plus language-aware terms for FTS retrieval."""
    text = _entry_folded_text(entry)
    terms = " ".join(sorted(_search_words(text, language)))
    return f"{text} {terms}"


def _storage_json(value: object) -> str:
    """Encode JSON fields compactly while keeping their text inspectable in SQLite."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


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


def _require_artifact(row: sqlite3.Row | None, path: Path) -> sqlite3.Row:
    """Return the artifact row or report an incomplete SQLite index."""
    if row is None:
        msg = f"Invalid Lens SQLite index: {path}: missing artifact metadata"
        raise LensError(msg)
    return row


@dataclass(frozen=True, slots=True)
class IndexMetadata:
    """Record how and from which sources an index was built."""

    sphinx_version: str = ""
    extensions: tuple[str, ...] = ()
    built_at: str = ""
    git_commit: str | None = None
    documents: dict[str, str] = field(default_factory=dict)
    language: str = ""
    build_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class Anchor:
    """Record a document-local anchor needed to resolve and classify links."""

    document: str
    anchor: str
    parent: str
    text: str
    order: int


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


def _link_document(source: str) -> str:
    """Return the document that owns a link source location."""
    return source.partition("#")[0]


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
        document_hashes: dict[str, str] | None = None,
        anchors: list[Anchor] | None = None,
        _database_path: Path | None = None,
    ) -> None:
        """Create a Lens from already extracted entries and links."""
        self.source = source
        self._entries: tuple[Entry, ...] | None = tuple(entries) if _database_path is None else None
        self._links: tuple[Link, ...] | None = tuple(links) if _database_path is None else None
        self._database_path = _database_path
        self.metadata = metadata or IndexMetadata()
        self.index_path = index_path
        self.no_search = frozenset(no_search)
        self.documents = documents or {}
        self.document_hashes = document_hashes or {}
        self.anchors = anchors or []
        self.warning_count = 0
        self._by_ref = {entry.ref: entry for entry in entries}

    @property
    def entries(self) -> tuple[Entry, ...]:
        """Return every entry, loading the complete table only when requested."""
        if self._entries is None:
            self._entries = tuple(self._select_entries(_SELECT_ALL_ENTRIES))
            self._by_ref = {entry.ref: entry for entry in self._entries}
        return self._entries

    @property
    def links(self) -> tuple[Link, ...]:
        """Return every link, loading the complete table only when requested."""
        if self._links is None:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT source, target, label, kind FROM links ORDER BY source, target, label, kind"
                )
                self._links = tuple(Link(*row) for row in rows)
        return self._links

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self._database_path is None:
            msg = "This Lens has no SQLite artifact"
            raise LensError(msg)
        connection = sqlite3.connect(f"file:{self._database_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    @classmethod
    def open(cls, path: str | Path = ".") -> Self:
        """Load an index file or discover it below a project directory."""
        index_path = Path(path)
        if index_path.is_dir():
            candidates = _index_candidates(index_path.resolve())
            found = next((candidate for candidate in candidates if candidate.is_file()), None)
            if found is None:
                legacy = next(
                    (candidate for candidate in _legacy_json_candidates(index_path.resolve()) if candidate.is_file()),
                    None,
                )
                if legacy is not None:
                    cls._raise_legacy_json(legacy)
                index_path = candidates[1]
            else:
                index_path = found
        index_path = index_path.resolve()
        if index_path.suffix == ".json":
            cls._raise_legacy_json(index_path)
        if not index_path.is_file():
            msg = f"Lens index not found: {index_path}"
            raise LensError(msg)
        try:
            connection = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
        except sqlite3.OperationalError as error:
            msg = f"Cannot open Lens index: {index_path}: {error}"
            raise LensError(msg) from error
        connection.row_factory = sqlite3.Row
        try:
            artifact = _require_artifact(connection.execute("SELECT * FROM artifact").fetchone(), index_path)
            if artifact["schema_version"] != INDEX_VERSION:
                msg = (
                    f"Unsupported Lens index version: {artifact['schema_version']!r}; "
                    "rebuild the index with the current version"
                )
                raise LensError(msg)
            document_rows = connection.execute("SELECT name, title, metadata FROM documents")
            documents = {
                row["name"]: DocumentInfo(title=row["title"], metadata=json.loads(row["metadata"]))
                for row in document_rows
            }
            document_hashes = {
                row["name"]: row["source_hash"] for row in connection.execute("SELECT name, source_hash FROM documents")
            }
        except sqlite3.DatabaseError as error:
            msg = f"Invalid Lens SQLite index: {index_path}: {error}"
            raise LensError(msg) from error
        finally:
            connection.close()
        lens = cls(
            source=artifact["source"],
            entries=[],
            links=[],
            metadata=IndexMetadata(
                sphinx_version=artifact["sphinx_version"],
                extensions=tuple(json.loads(artifact["extensions"])),
                built_at=artifact["built_at"],
                git_commit=artifact["git_commit"],
                documents=json.loads(artifact["source_documents"]),
                language=artifact["language"],
                build_fingerprint=artifact["build_fingerprint"],
            ),
            index_path=index_path,
            no_search=json.loads(artifact["no_search"]),
            documents=documents,
            document_hashes=document_hashes,
            _database_path=index_path,
        )
        lens._warn_if_stale()
        return lens

    def write(self, path: str | Path) -> Path:
        """Write this Lens to a temporary SQLite database and replace atomically."""
        index_path = Path(path).resolve()
        index_path.parent.mkdir(parents=True, exist_ok=True)
        existing_mode = stat.S_IMODE(index_path.stat().st_mode) if index_path.exists() else None
        while True:
            temporary_path = index_path.with_name(f".{index_path.name}.{secrets.token_hex(8)}.tmp")
            try:
                handle = os.open(temporary_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
            except FileExistsError:
                continue
            os.close(handle)
            break
        try:
            self._write_database(temporary_path)
            if existing_mode is not None:
                temporary_path.chmod(existing_mode)
            temporary_path.replace(index_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
        self.index_path = index_path
        self._database_path = index_path
        return index_path

    @staticmethod
    def supports_incremental(path: Path, fingerprint: str) -> bool:
        """Return whether ``path`` can accept a document-scoped update."""
        if not path.is_file():
            return False
        try:
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
                row = connection.execute("SELECT schema_version, build_fingerprint FROM artifact").fetchone()
        except sqlite3.DatabaseError:
            return False
        return row == (INDEX_VERSION, fingerprint)

    @staticmethod
    def load_anchors(path: Path) -> list[Anchor]:
        """Load persisted anchors from a compatible artifact."""
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
            rows = connection.execute(
                "SELECT document, anchor, parent, text, source_order FROM anchors ORDER BY document, source_order"
            )
            return [Anchor(row[0], row[1], row[2], row[3], row[4]) for row in rows]

    def write_incremental(  # noqa: PLR0913
        self,
        path: str | Path,
        *,
        changed_documents: set[str],
        document_entries: list[Entry],
        objects: list[Entry],
        links: list[Link],
        known_locations: set[str],
    ) -> Path:
        """Atomically replace ``path`` after updating only changed document-owned rows."""
        index_path = Path(path).resolve()
        if not self.supports_incremental(index_path, self.metadata.build_fingerprint):
            msg = f"Cannot incrementally update incompatible Lens index: {index_path}"
            raise LensError(msg)
        existing_mode = stat.S_IMODE(index_path.stat().st_mode)
        while True:
            temporary_path = index_path.with_name(f".{index_path.name}.{secrets.token_hex(8)}.tmp")
            try:
                handle = os.open(temporary_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
            except FileExistsError:
                continue
            os.close(handle)
            break
        try:
            copyfile(index_path, temporary_path)
            self._update_database(
                temporary_path,
                changed_documents=changed_documents,
                document_entries=document_entries,
                objects=objects,
                links=links,
                known_locations=known_locations,
            )
            temporary_path.chmod(existing_mode)
            temporary_path.replace(index_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
        self.index_path = index_path
        self._database_path = index_path
        return index_path

    def _update_database(  # noqa: PLR0913
        self,
        path: Path,
        *,
        changed_documents: set[str],
        document_entries: list[Entry],
        objects: list[Entry],
        links: list[Link],
        known_locations: set[str],
    ) -> None:
        language = _search_language(self.metadata.language)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.row_factory = sqlite3.Row
            for document in changed_documents:
                self._delete_document_entries(connection, document, language)
                connection.execute("DELETE FROM documents WHERE name = ?", (document,))
                connection.execute("DELETE FROM anchors WHERE document = ?", (document,))
            connection.executemany(
                "INSERT INTO documents(name, title, metadata, source_hash) VALUES (?, ?, ?, ?)",
                (
                    (name, record.title, _storage_json(record.metadata), self.document_hashes.get(name, ""))
                    for name, record in self.documents.items()
                    if name in changed_documents
                ),
            )
            connection.executemany(
                "INSERT INTO anchors(document, anchor, parent, text, source_order) VALUES (?, ?, ?, ?, ?)",
                (
                    (anchor.document, anchor.anchor, anchor.parent, anchor.text, anchor.order)
                    for anchor in self.anchors
                    if anchor.document in changed_documents
                ),
            )
            for entry in document_entries:
                self._insert_entry(connection, entry, language)
            self._replace_objects(connection, objects, language)
            connection.executemany(
                "DELETE FROM links WHERE source_document = ?",
                ((document,) for document in changed_documents),
            )
            connection.executemany(
                "INSERT INTO links(source, source_document, target, label, kind) VALUES (?, ?, ?, ?, ?)",
                (
                    (link.source, _link_document(link.source), link.target, link.label, link.kind)
                    for link in sorted(set(links), key=lambda link: (link.source, link.target, link.label, link.kind))
                ),
            )
            valid_targets = known_locations | {f"{anchor.document}#{anchor.anchor}" for anchor in self.anchors}
            for row in connection.execute("SELECT rowid, target, kind FROM links WHERE kind != 'external'"):
                kind = "internal" if row["target"] in valid_targets else "unresolved"
                if kind != row["kind"]:
                    connection.execute("UPDATE links SET kind = ? WHERE rowid = ?", (kind, row["rowid"]))
            connection.execute(
                """UPDATE artifact SET source = ?, sphinx_version = ?, extensions = ?, built_at = ?, git_commit = ?,
                language = ?, no_search = ?, source_documents = ?, build_fingerprint = ?""",
                (
                    self.source,
                    self.metadata.sphinx_version,
                    _storage_json(self.metadata.extensions),
                    self.metadata.built_at,
                    self.metadata.git_commit,
                    self.metadata.language,
                    _storage_json(sorted(self.no_search)),
                    _storage_json(self.metadata.documents),
                    self.metadata.build_fingerprint,
                ),
            )
            connection.execute("INSERT INTO entries_fts(entries_fts) VALUES ('optimize')")
            connection.execute("INSERT INTO entries_trigram(entries_trigram) VALUES ('optimize')")
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA optimize")

    def _delete_document_entries(
        self, connection: sqlite3.Connection, document: str, language: SearchLanguage | None
    ) -> None:
        rows = connection.execute("SELECT id, * FROM entries WHERE document = ? AND kind != 'object'", (document,))
        for row in rows:
            self._delete_fts_entry(connection, row, language)
        connection.execute("DELETE FROM entries WHERE document = ? AND kind != 'object'", (document,))

    def _replace_objects(
        self, connection: sqlite3.Connection, objects: list[Entry], language: SearchLanguage | None
    ) -> None:
        existing = {row["ref"]: row for row in connection.execute("SELECT id, * FROM entries WHERE kind = 'object'")}
        current = {entry.ref: entry for entry in objects}
        for ref, row in existing.items():
            if ref not in current:
                self._delete_fts_entry(connection, row, language)
                connection.execute("DELETE FROM entries WHERE id = ?", (row["id"],))
        for ref, entry in current.items():
            row = existing.get(ref)
            values = self._entry_values(entry, self.no_search)
            if row is None:
                self._insert_entry(connection, entry, language)
            elif values != self._stored_entry_values(row):
                self._delete_fts_entry(connection, row, language)
                connection.execute(
                    """UPDATE entries SET kind = ?, title = ?, text = ?, document = ?, anchor = ?, source_order = ?,
                    parent = ?, domain = ?, object_type = ?, name = ?, normalized_ref = ?, normalized_title = ?,
                    normalized_name = ?, searchable = ? WHERE id = ?""",
                    (*values[1:], row["id"]),
                )
                self._insert_fts_entry(connection, row["id"], entry, language)

    @staticmethod
    def _entry_values(entry: Entry, no_search: set[str] | frozenset[str] = frozenset()) -> tuple[object, ...]:
        return (
            entry.ref,
            entry.kind,
            entry.title,
            entry.text,
            entry.document,
            entry.anchor,
            entry.order,
            entry.parent,
            entry.domain,
            entry.object_type,
            entry.name,
            _fold_text(entry.ref),
            _fold_text(entry.title),
            _fold_text(entry.name or ""),
            entry.document not in no_search,
        )

    def _stored_entry_values(self, row: sqlite3.Row) -> tuple[object, ...]:
        return (
            row["ref"],
            row["kind"],
            row["title"],
            row["text"],
            row["document"],
            row["anchor"],
            row["source_order"],
            row["parent"],
            row["domain"],
            row["object_type"],
            row["name"],
            row["normalized_ref"],
            row["normalized_title"],
            row["normalized_name"],
            bool(row["searchable"]),
        )

    def _insert_entry(self, connection: sqlite3.Connection, entry: Entry, language: SearchLanguage | None) -> None:
        cursor = connection.execute(
            """INSERT INTO entries(
                ref, kind, title, text, document, anchor, source_order, parent, domain, object_type, name,
                normalized_ref, normalized_title, normalized_name, searchable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            self._entry_values(entry, self.no_search),
        )
        self._insert_fts_entry(connection, cast("int", cursor.lastrowid), entry, language)

    def _insert_fts_entry(
        self, connection: sqlite3.Connection, entry_id: int, entry: Entry, language: SearchLanguage | None
    ) -> None:
        if entry.document not in self.no_search:
            connection.execute(
                "INSERT INTO entries_fts(rowid, searchable) VALUES (?, ?)",
                (entry_id, _entry_search_text(entry, language)),
            )
            connection.execute(
                "INSERT INTO entries_trigram(rowid, searchable) VALUES (?, ?)", (entry_id, _entry_folded_text(entry))
            )

    def _delete_fts_entry(
        self, connection: sqlite3.Connection, row: sqlite3.Row, language: SearchLanguage | None
    ) -> None:
        if not row["searchable"]:
            return
        entry = self._entry_from_row(row)
        connection.execute(
            "INSERT INTO entries_fts(entries_fts, rowid, searchable) VALUES ('delete', ?, ?)",
            (row["id"], _entry_search_text(entry, language)),
        )
        connection.execute(
            "INSERT INTO entries_trigram(entries_trigram, rowid, searchable) VALUES ('delete', ?, ?)",
            (row["id"], _entry_folded_text(entry)),
        )

    @staticmethod
    def _raise_legacy_json(path: Path) -> None:
        msg = f"JSON Lens indexes are no longer supported: {path}; rebuild the index to create {INDEX_FILENAME}"
        raise LensError(msg)

    def _write_database(self, path: Path) -> None:
        language = _search_language(self.metadata.language)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT INTO artifact VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    INDEX_VERSION,
                    self.source,
                    self.metadata.sphinx_version,
                    _storage_json(self.metadata.extensions),
                    self.metadata.built_at,
                    self.metadata.git_commit,
                    self.metadata.language,
                    _storage_json(sorted(self.no_search)),
                    _storage_json(self.metadata.documents),
                    self.metadata.build_fingerprint,
                ),
            )
            connection.executemany(
                "INSERT INTO documents(name, title, metadata, source_hash) VALUES (?, ?, ?, ?)",
                (
                    (name, document.title, _storage_json(document.metadata), self.document_hashes.get(name, ""))
                    for name, document in sorted(self.documents.items())
                ),
            )
            connection.executemany(
                "INSERT INTO anchors(document, anchor, parent, text, source_order) VALUES (?, ?, ?, ?, ?)",
                ((anchor.document, anchor.anchor, anchor.parent, anchor.text, anchor.order) for anchor in self.anchors),
            )
            connection.executemany(
                """INSERT INTO entries(
                    ref, kind, title, text, document, anchor, source_order, parent, domain, object_type, name,
                    normalized_ref, normalized_title, normalized_name, searchable
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    (
                        entry.ref,
                        entry.kind,
                        entry.title,
                        entry.text,
                        entry.document,
                        entry.anchor,
                        entry.order,
                        entry.parent,
                        entry.domain,
                        entry.object_type,
                        entry.name,
                        _fold_text(entry.ref),
                        _fold_text(entry.title),
                        _fold_text(entry.name or ""),
                        entry.document not in self.no_search,
                    )
                    for entry in self.entries
                ),
            )
            connection.executemany(
                "INSERT INTO entries_fts(rowid, searchable) VALUES (?, ?)",
                (
                    (entry_id, _entry_search_text(entry, language))
                    for entry_id, entry in enumerate(self.entries, start=1)
                    if entry.document not in self.no_search
                ),
            )
            connection.executemany(
                "INSERT INTO entries_trigram(rowid, searchable) VALUES (?, ?)",
                (
                    (entry_id, _entry_folded_text(entry))
                    for entry_id, entry in enumerate(self.entries, start=1)
                    if entry.document not in self.no_search
                ),
            )
            connection.executemany(
                "INSERT INTO links(source, source_document, target, label, kind) VALUES (?, ?, ?, ?, ?)",
                ((link.source, _link_document(link.source), link.target, link.label, link.kind) for link in self.links),
            )
            connection.execute("INSERT INTO entries_fts(entries_fts) VALUES ('optimize')")
            connection.execute("INSERT INTO entries_trigram(entries_trigram) VALUES ('optimize')")
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA optimize")

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
        if self._database_path is None:
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
        elif name is not None:
            domain, separator, object_type = target.partition(":")
            matches = (
                self._select_entries(
                    _SELECT_OBJECT_IDENTITY,
                    (domain, object_type, name),
                )
                if separator
                else []
            )
        else:
            exact = self._select_entries(
                _SELECT_ENTRY_REF,
                (target,),
            )
            if exact:
                return exact[0]
            matches = self._select_entries(
                _SELECT_OBJECT_NAME,
                (target,),
            )
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
        candidates = self._locate_candidates(search_needle, search_language, regex=regex)
        for entry in candidates:
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
            results.append(
                SearchResult(
                    entry=entry,
                    score=score,
                    excerpt=self._excerpt(entry.text, search_needle, words=words, language=search_language),
                )
            )
        results.sort(key=lambda result: (-result.score, result.entry.ref))
        return self._distinct_results(results, limit)

    def _locate_candidates(
        self,
        search_needle: str,
        language: SearchLanguage | None,
        *,
        regex: bool,
    ) -> tuple[Entry, ...] | list[Entry]:
        if self._database_path is None:
            return self.entries
        if regex:
            return self._select_entries(_SELECT_SEARCHABLE_ENTRIES)
        match = _fts_query(search_needle, language)
        trigram_match = _trigram_query(search_needle)
        if not trigram_match:
            return self._select_entries(_SELECT_SEARCHABLE_ENTRIES)
        candidates = self._select_entries(_SELECT_TRIGRAM_ENTRIES, (trigram_match,))
        if match:
            candidates.extend(self._select_entries(_SELECT_FTS_ENTRIES, (match,)))
        return list({entry.ref: entry for entry in candidates}.values())

    def _select_entries(self, sql: str, parameters: tuple[object, ...] = ()) -> list[Entry]:
        with self._connect() as connection:
            return [self._entry_from_row(row) for row in connection.execute(sql, parameters)]

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> Entry:
        return Entry(
            ref=row["ref"],
            kind=row["kind"],
            title=row["title"],
            text=row["text"],
            document=row["document"],
            anchor=row["anchor"],
            order=row["source_order"],
            parent=row["parent"],
            domain=row["domain"],
            object_type=row["object_type"],
            name=row["name"],
        )

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
        if self._database_path is not None:
            placeholders = ", ".join("?" for _ in locations)
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT source, target, label, kind FROM links "  # noqa: S608
                    f"WHERE source IN ({placeholders}) ORDER BY source, target, label, kind",
                    tuple(locations),
                )
                return tuple(Link(*row) for row in rows)
        return tuple(link for link in self.links if link.source in locations)

    def linked(self, target: str) -> LinkSet:
        """Return incoming and outgoing references for a target."""
        entry = self.resolve(target)
        outgoing = self.references(target)
        if self._database_path is not None:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT source, target, label, kind FROM links "
                    "WHERE target = ? ORDER BY source, target, label, kind",
                    (entry.location,),
                )
                return LinkSet(incoming=tuple(Link(*row) for row in rows), outgoing=outgoing)
        incoming = tuple(link for link in self.links if link.target == entry.location)
        return LinkSet(incoming=incoming, outgoing=outgoing)

    def _children(self, parent: str) -> list[Entry]:
        if self._database_path is not None:
            return self._select_entries(
                _SELECT_CHILDREN,
                (parent,),
            )
        return sorted((entry for entry in self.entries if entry.parent == parent), key=lambda entry: entry.sort_key)

    def _descendants(self, parent: str) -> list[Entry]:
        """Return every nested entry below ``parent``, depth first in source order."""
        if self._database_path is not None:
            descendants = self._select_entries(
                _SELECT_DESCENDANTS,
                (parent,),
            )
            by_parent: dict[str, list[Entry]] = {}
            for entry in descendants:
                if entry.parent is not None:
                    by_parent.setdefault(entry.parent, []).append(entry)
            for children in by_parent.values():
                children.sort(key=lambda entry: entry.sort_key)

            def walk(current: str) -> list[Entry]:
                return [nested for child in by_parent.get(current, ()) for nested in (child, *walk(child.ref))]

            return walk(parent)
        return [nested for child in self._children(parent) for nested in (child, *self._descendants(child.ref))]

    def as_dict(self) -> dict[str, Any]:
        """Return the complete index model as JSON-compatible values."""
        return {
            "version": INDEX_VERSION,
            "source": self.source,
            "metadata": asdict(self.metadata),
            "no_search": sorted(self.no_search),
            "documents": {docname: asdict(document) for docname, document in sorted(self.documents.items())},
            "entries": [asdict(entry) for entry in self.entries],
            "links": [asdict(link) for link in self.links],
        }

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
    def _excerpt(
        text: str,
        needle: str,
        *,
        words: set[str] | None = None,
        language: SearchLanguage | None = None,
        width: int = 180,
    ) -> str:
        normalized = " ".join(text.split())
        position = normalized.casefold().find(needle)
        if position < 0:
            position = _fold_text(normalized).find(_fold_text(needle))
        if position < 0 and words:
            for match in re.finditer(r"\w+", normalized, flags=re.UNICODE):
                term = _fold_text(match.group())
                stemmed = language.stem(term) if language is not None else term
                if stemmed in words or (language is None and any(word in term for word in words)):
                    position = match.start()
                    break
        position = max(position, 0)
        start = max(0, position - width // 3)
        excerpt = normalized[start : start + width]
        if start:
            excerpt = f"...{excerpt}"
        if start + width < len(normalized):
            excerpt = f"{excerpt}..."
        return excerpt
