# CLI and Python API (Reference)

Sphinx Lens stores a versioned JSON index independent of Sphinx's pickled build
environment. A project directory discovers `.sphinx-lens/index.json`; a direct
path can point to any index file.

## CLI

```text
sphinx-lens build SOURCE [--output PATH]
sphinx-lens locate QUERY [--index PATH] [--limit N]
sphinx-lens inspect TARGET [--index PATH]
sphinx-lens read TARGET [--index PATH]
sphinx-lens links TARGET [--index PATH]
```

`build` uses the Sphinx `dummy` builder, so project extensions and domains run
without rendering HTML. `locate` prints ranked matches. `inspect` and `links`
return JSON; `read` returns normalized plain text.

Targets use one of these forms:

- Document: `guide/network`
- Section: `guide/network#timeouts`
- Domain object: `py:class:example.Client`

## Python API

```python
from sphinx_lens import Lens, build

lens = build("docs/", "artifacts/docs-index.json")
lens = Lens.open("artifacts/docs-index.json")

entry = lens.resolve("guide/network#timeouts")
client = lens.resolve("py:class", "example.Client")
results = lens.locate("connection timeout", limit=5)
text = lens.read(entry.ref)
children = lens.children("guide/network")
outgoing = lens.references(entry.ref)
both_directions = lens.linked(entry.ref)
```

`Entry.location` maps domain objects back to their physical `document#anchor`.
Links use physical locations so incoming references to a section and to an
object at the same Sphinx anchor can be combined.

## Index Model

The version 1 JSON document contains:

- `source`: absolute source directory used for the build.
- `entries`: documents, sections, and domain objects with normalized text and
  parent relationships.
- `links`: internal, external, and unresolved directed references.

The index is intentionally a portable intermediate representation. It does not
require Neo4j, RDF, an embedding model, or an LLM.
