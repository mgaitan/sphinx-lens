# How it works

Sphinx Lens runs as a Sphinx build. Most of the rest follows from that one
choice.

Writing a parser is the obvious approach, and it does not survive contact with
real projects. A Sphinx project is RST and MyST together, expanded by autodoc,
transformed by extensions, organized by domains the project may have defined
itself, with cross-references that only resolve in the context of the module or
class they appear in. Reimplementing part of that means eventually
reimplementing all of it.

So the `lens` builder runs after Sphinx has read every source, expanded every
extension, populated every domain, and resolved every reference. By then the
hard work is finished, and what remains is writing it down.

```{mermaid}
flowchart LR
    A["RST / MyST / notebooks / autodoc"] --> B["Sphinx environment"]
    C["Project extensions and domains"] --> B
    B --> D["Sphinx resolves cross-references"]
    D --> E["lens builder extracts scopes and links"]
    E --> J["_build/lens/index.sqlite"]
    J --> F["CLI"]
    J --> G["Python API"]
    J --> H["JSON exports for jq / rg"]
    F --> I["Agent or developer"]
    G --> I
    H --> I
```

The index therefore inherits every format and extension the project already
supports, at no cost. A project that adds a custom domain next year will get
that domain in its index without Sphinx Lens knowing it exists.

The output lives under `_build/lens/` for the same reason. It is a build
artifact like HTML or linkcheck results, so it inherits their lifecycle: `make
clean` removes it, CI caches it, and publishing it requires no new convention.

Lens also accepts `lens_no_search`, a list of source-file globs for generated
pages that should remain available through navigation without contributing to
`locate` results.

### Incremental builds

After its first SQLite build, Lens records each document's source hash together
with the anchors and link sources that document owns. A later Sphinx build
copies the complete artifact, replaces the changed document scopes and their FTS
rows in one transaction, updates changed domain objects, and reclassifies local
links against the current anchor set. The copy replaces the published artifact
only after SQLite closes it, so an interrupted update leaves the previous index
available.

Lens rebuilds the complete artifact when the SQLite schema or Lens-relevant
Sphinx settings change. This includes the Sphinx version, enabled extensions,
language, and `lens_no_search`. A clean rebuild also remains the fallback for
any build where Sphinx reports every document as needing output.

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
Domain objects are addressed by meaning, as `py:class:example.Client`, and also
keep the physical `location` where they are documented. Callers can therefore
ask for a thing by name while link traversal stays anchored to real documents,
which is what lets an incoming reference to a section and to the object defined
at the same anchor be combined instead of split.

Each entry stores only its own text, excluding nested sections and objects, and
`read` composes a scope back together by walking the hierarchy in source order.
Without that split, a search for a phrase would match the paragraph, the section
containing it, and the whole document, and all three would compete for the same
result slot.

## Why a separate artifact

Sphinx already emits several representations. The honest question is why none of
them is enough:

| Artifact | What it provides | What Lens adds |
| --- | --- | --- |
| `objects.inv` | Domain objects and target locations | Section scopes, text, hierarchy, and directed links |
| `searchindex.js` | Theme-facing lexical search data | Stable domain references and a format independent of HTML builders |
| `doctrees/` | Complete docutils trees | A versioned SQLite schema that does not unpickle project-controlled Python objects |

The compiled link graph is the real difference. Nothing else Sphinx writes lets
a caller ask what a scope cites and what cites it without rerunning Sphinx or
scraping generated HTML.

### Text exports and indexed retrieval

An `llms-full.txt` file concatenates a documentation site into one text export.
Projects such as
[`sphinx-llms-txt`](https://github.com/jdillard/sphinx-llms-txt) and
[`NVIDIA/sphinx-llm`](https://github.com/NVIDIA/sphinx-llm) generate this kind of
output for Sphinx.

A Lens index keeps documents, sections, and domain objects separately
addressable. A consumer resolves a reference, reads that scope, and can follow
its hierarchy and links. This avoids sending the full corpus with every request
or reconstructing structure from HTML.

Both artifacts can be published beside the HTML documentation. The text export
supports bulk ingestion, while the Lens index supports selecting and traversing
individual scopes.

The text is the honest weakness. `astext()` flattens prose, code blocks, tables,
and admonitions into one undifferentiated string, which is a strange thing for a
structure-aware index to do. Entries are addressable and nested; the text inside
them is flat. Image nodes are preserved as Markdown-style `![alt](uri)` tokens so
search and consumers do not lose the image's destination or alternative text.

## Deliberate boundaries

Some things this project chooses to leave out, and why.

Sphinx stores its environment as a Python pickle, and unpickling it executes
project-controlled code. Lens instead writes a SQLite database that can be read
without importing the Sphinx project or running its code.

`locate` is lexical. It folds accents and uses Sphinx's configured stemmer when
one exists, then turns a phrase into a stable reference so the caller can read
and traverse from there. Similarity search belongs to a caller that has a model,
and building it into the format would date the format.

Staleness checks need the source tree. An index written outside that tree keeps
its content portable and warns when the source path is unavailable, rather than
claiming that its hashes were checked.

Precise and ad hoc analysis is covered by `--regex`, `--kind`, `--domain`, and
JSON output. `dump --json`, `entries --json`, and `links --all --json` keep the
model available to `jq` and `rg` without making SQL part of the public workflow.

The index is a file. A build produces it, CI can cache or publish it, and any
process can read it without a daemon, a port, or credentials. Anything that
speaks a protocol is an adapter over `Lens`, and adapters do not get to shape
the data model.

SQLite keeps the artifact auditable with standard tools, but the database file
is neither meaningfully diffable nor directly greppable. The JSON export
commands provide the textual interchange format. In return, canonical
references, hierarchy, and links use B-tree indexes, while FTS5 narrows normal
text searches before Lens applies its existing ranking and excerpt rules in
Python. [Real-world corpora](corpus_evaluation.md) records the measured costs.
