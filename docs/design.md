# How it works

Sphinx Lens is a builder, not a parser. That single decision explains most of
what follows.

Parsing documentation yourself is the obvious approach and the wrong one. A
Sphinx project is not a pile of RST files: it is RST *and* MyST, expanded by
autodoc, transformed by a dozen extensions, organized by domains the project may
have defined itself, with cross-references that only resolve in the context of
the module or class they appear in. Reimplementing any part of that means
reimplementing all of it, badly, forever.

So Sphinx Lens does not. It runs as a build, after Sphinx has already read every
source, expanded every extension, populated every domain, and resolved every
reference. At that point the hard work is done and the job is only to write it
down.

```{mermaid}
flowchart LR
    A["RST / MyST / notebooks / autodoc"] --> B["Sphinx environment"]
    C["Project extensions and domains"] --> B
    B --> D["Sphinx resolves cross-references"]
    D --> E["lens builder extracts scopes and links"]
    E --> J["_build/lens/index.json"]
    J --> F["CLI"]
    J --> G["Python API"]
    J --> H["jq / rg"]
    F --> I["Agent or developer"]
    G --> I
    H --> I
```

The consequence worth naming: the index inherits, for free and permanently,
every format and extension the project already supports. A project that adds a
custom domain next year gets that domain in its index without Sphinx Lens
knowing it exists.

Living under `_build/lens/` follows from the same choice. The index is a build
output like HTML or linkcheck results, so it inherits their lifecycle — `make
clean` removes it, CI caches it, and publishing it needs no new convention.

## The model

Three kinds of entry, arranged in a hierarchy, connected by a directed graph.

```{mermaid}
flowchart TD
    D["Document"] -->|contains| S["Section"]
    S -->|contains| SS["Nested section"]
    D -->|defines| O["Domain object"]
    S -->|defines| O
    O -->|contains| OO["Nested object"]
    D -. "internal / external / unresolved" .-> D2["Document or target"]
    S -. "references" .-> O
    O -. "references" .-> S
```

Documents and sections are addressed physically, as `guide/network#timeouts`.
Domain objects are addressed by meaning, as `py:class:example.Client`, but also
keep the physical `location` where they are documented. Callers therefore get to
ask for a thing by name while link traversal stays anchored to real documents —
and an incoming reference to a section and to the object defined at the same
anchor can be combined rather than split.

Each entry stores **only its own text**, excluding nested sections and objects.
`read` composes a scope back together by walking the hierarchy. This is not an
optimization; it is what stops an ancestor and its most specific descendant from
showing up as two hits for the same paragraph, which is the failure mode that
makes naive documentation search unusable.

## Why a separate artifact

Sphinx already emits several representations, and the honest question is why
none of them is enough:

| Artifact | What it provides | What Lens adds |
| --- | --- | --- |
| `objects.inv` | Domain objects and target locations | Section scopes, text, hierarchy, and directed links |
| `searchindex.js` | Theme-facing lexical search data | Stable domain references and a format independent of HTML builders |
| `doctrees/` | Complete docutils trees | A versioned JSON contract that does not unpickle project-controlled Python objects |

The compiled link graph is the real difference. Nothing else Sphinx writes lets
a caller ask what a scope cites and what cites it without rerunning Sphinx or
scraping generated HTML.

The text is the honest weakness. `astext()` flattens prose, code blocks, tables,
and admonitions into the same undifferentiated string, which is a strange thing
for a structure-aware index to do. Preserving source ranges, and reading back
original markup instead of normalized text, needs its own design and is the most
valuable thing a later index version could add.

## Deliberate boundaries

Things this project chooses *not* to do, and why:

**JSON, not Sphinx's pickle.** Unpickling executes project-controlled Python.
An artifact meant to be published, cached, and read by other processes and other
languages cannot require that.

**Lexical search, not embeddings.** `locate` exists to turn a phrase into a
stable reference so the caller can read and traverse from there. Similarity
search is a decision for a caller with a model, not a property of an index
format that should still be readable in five years.

**Regex and shell composition, not a query language.** `--regex`, `--kind`,
`--domain`, `--json` and `jq` cover precise and ad hoc analysis. A bespoke query
language would be a second thing to learn and a second thing to maintain.

**MCP as an adapter, not the core.** A server over `Lens` is a small amount of
code. Letting a protocol shape the data model would not be.

**JSON now, SQLite later.** JSON is auditable, diffable, and greppable, which is
what a proof of concept needs. Repeated queries against large corpora pay for it
in parse time, and SQLite with FTS5 is the compatible next store — it also
replaces the hand-tuned ranking with BM25. A remote libSQL database is a
deployment detail of that store, not a third format.
