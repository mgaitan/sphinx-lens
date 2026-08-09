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
    E --> J["_build/lens/index.json"]
    J --> F["CLI"]
    J --> G["Python API"]
    J --> H["jq / rg"]
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
| `doctrees/` | Complete docutils trees | A versioned JSON contract that does not unpickle project-controlled Python objects |

The compiled link graph is the real difference. Nothing else Sphinx writes lets
a caller ask what a scope cites and what cites it without rerunning Sphinx or
scraping generated HTML.

### Relationship to `llms.txt`

An `llms-full.txt` export is useful when a consumer needs one text snapshot of
an entire documentation site. Projects such as
[`sphinx-llms-txt`](https://github.com/jdillard/sphinx-llms-txt) and
[`NVIDIA/sphinx-llm`](https://github.com/NVIDIA/sphinx-llm) provide that output
for Sphinx projects.

Lens answers a different retrieval question: how can a consumer read one
compiled scope and traverse its relationships without loading the whole corpus?
It preserves stable Sphinx references, hierarchy, domain objects, and the link
graph so an agent can retrieve scopes on demand. It does not generate
`llms.txt`, and those exporters do not need to become structural indexes. A
project can publish both beside its HTML: a flat export for bulk ingestion and a
Lens index for precise navigation.

The text is the honest weakness. `astext()` flattens prose, code blocks, tables,
and admonitions into one undifferentiated string, which is a strange thing for a
structure-aware index to do. Entries are addressable and nested; the text inside
them is flat.

## Deliberate boundaries

Some things this project chooses to leave out, and why.

Sphinx stores its environment as a Python pickle, and unpickling it executes
project-controlled code. An artifact meant to be published, cached, and read by
other processes and other languages cannot require that, so the index is JSON.

`locate` is lexical. Its job is to turn a phrase into a stable reference so the
caller can read and traverse from there. Similarity search belongs to a caller
that has a model, and building it into the format would date the format.

Precise and ad hoc analysis is covered by `--regex`, `--kind`, `--domain`,
`--json`, and `jq`. A query language of its own would be one more thing to learn
and one more thing to maintain.

The index is a file. A build produces it, a repository can commit it, and any
process can read it without a daemon, a port, or credentials. Anything that
speaks a protocol is an adapter over `Lens`, and adapters do not get to shape
the data model.

JSON is auditable, diffable, and greppable, which is what an artifact meant to
be inspected should be. It is also parsed in full on every open, so repeated
queries against a large corpus pay for that readability in startup time.
[Real-world corpora](corpus_evaluation.md) measures how much.
