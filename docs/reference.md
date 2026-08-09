# CLI and Python API

The complete surface: one builder, five commands, one class, and the shape of
the file they all read. [Getting started](getting_started.md) is the guided
version of the same material.

Every query command takes `--index`, which accepts either a builder output
directory containing `index.json` or a direct path to the file itself.

## Sphinx builder

The installed package registers a native builder through Sphinx's builder entry
point. No `conf.py` change is required:

```console
sphinx-build -b lens docs/ docs/_build/lens/
```

The builder loads the same sources, extensions, domains, objects, and references
as every other Sphinx build. Its only output is
`docs/_build/lens/index.json`. A Makefile can expose the command as `make lens`.

## CLI

```text
sphinx-lens build SOURCE [--output DIRECTORY] [--fail-on-warning]
sphinx-lens locate QUERY [--index PATH] [--limit N]
                   [--regex] [--kind KIND] [--domain DOMAIN] [--json]
sphinx-lens inspect TARGET [--index PATH]
sphinx-lens read TARGET [--index PATH]
sphinx-lens links TARGET [--index PATH]
```

`sphinx-lens build` is a convenience wrapper around the native builder. It
writes `SOURCE/_build/lens/index.json` by default. `--fail-on-warning` applies
Sphinx's warning-as-error policy.

`locate` normally ranks exact names, headings, body phrases, and unordered token
matches. `--regex` interprets the query as a case-insensitive Python regular
expression. Repeat `--kind` to select documents, sections, or objects; use
`--domain py` to restrict domain objects. `--json` returns structured results.

```bash
sphinx-lens locate "database transactions" -i docs/_build/lens
sphinx-lens locate 'QuerySet\.(get|filter)' --regex --kind object --domain py \
  --json -i docs/_build/lens
```

Targets use one of these forms:

- Document: `guide/network`
- Section: `guide/network#timeouts`
- Domain object: `py:class:example.Client`

## Shell composition

Use `jq` for structured predicates and projections over either search results or
the complete model:

```bash
sphinx-lens locate 'QuerySet\..*' --regex --kind object --json \
  -i docs/_build/lens \
  | jq -r '.[] | [.entry.ref, .score] | @tsv'

jq -r '.links[] | select(.kind == "unresolved") | .target' \
  docs/_build/lens/index.json \
  | sort | uniq -c | sort -nr
```

Use `rg` when a quick textual scan is enough and ranking or typed fields do not
matter:

```bash
rg -n -i 'transaction|atomic' docs/_build/lens/index.json
```

## Python API

```python
from sphinx_lens import Lens, build

lens = build("docs/", "artifacts/lens")
lens = Lens.open("artifacts/lens")

entry = lens.resolve("guide/network#timeouts")
client = lens.resolve("py:class", "example.Client")
results = lens.locate(
    r"Client\.(connect|close)",
    regex=True,
    kinds={"object"},
    domain="py",
)
text = lens.read(entry.ref)
children = lens.children("guide/network")
outgoing = lens.references(entry.ref)
both_directions = lens.linked(entry.ref)
```

`Entry.location` maps domain objects back to their physical `document#anchor`.
Links use physical locations so incoming references to a section and to an
object at the same Sphinx anchor can be combined.

## Index model

The version 2 JSON document contains:

- `source`: source directory relative to the artifact.
- `metadata`: Sphinx version, configured extensions, UTC build time, Git commit,
  and a SHA-256 hash for each source document.
- `entries`: documents, sections, and domain objects with normalized text and
  parent relationships.
- `links`: internal, external, and unresolved directed references.

`Lens.open()` warns when available local sources no longer match their hashes.
Missing sources do not prevent a published artifact from loading.

Documents, sections, and objects store only their own normalized text. `read`
reconstructs a scope by composing its descendants, avoiding repeated ancestor
content in search results. Markup distinctions such as code blocks and tables
are not preserved in version 2.

The index is intentionally a portable intermediate representation. `locate` is
a reference finder, not semantic similarity search; it does not require Neo4j,
RDF, an embedding model, or an LLM.
