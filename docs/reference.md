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

(search-exclusions)=
## Search exclusions

Lens follows Sphinx's file-wide search metadata. Add either `no-search` or
`nosearch` to a document's metadata to keep it out of `locate` results:

```rst
:no-search: true

Generated page
==============
```

MyST frontmatter uses the same keys:

```md
---
no-search: true
---
```

Generated documents that cannot carry metadata can be selected in `conf.py`:

```python
lens_no_search = ["**/index.md"]
```

Patterns match source-file paths relative to the Sphinx source directory. A
leading `**/` also matches a file at the source root. Metadata and configured
globs are additive: either one excludes the document. Excluded documents remain
in the index and work with `resolve`, `read`, `children`, and `links`; only
`locate` omits them.

## CLI

```text
sphinx-lens build SOURCE [--output DIRECTORY] [--conf-dir DIRECTORY]
                    [--doctree-dir DIRECTORY] [--fail-on-warning]
sphinx-lens locate QUERY [--index PATH] [--limit N]
                   [--regex] [--kind KIND] [--domain DOMAIN] [--under PATH] [--json]
sphinx-lens inspect TARGET [--no-text] [--index PATH]
sphinx-lens read TARGET [--index PATH]
sphinx-lens links TARGET [--index PATH]
```

`sphinx-lens build` is a convenience wrapper around the native builder. It
writes `SOURCE/_build/lens/index.json` by default. Use `--conf-dir` when
`conf.py` lives outside `SOURCE`, and `--doctree-dir` to keep Sphinx's cached
doctrees outside the source tree. `--fail-on-warning` applies Sphinx's
warning-as-error policy. The build summary includes the number of links
classified as unresolved, for example `(3 unresolved)`.

A local link is `internal` only when its document and anchor are known to the
built index. A link to an existing document with a missing anchor is therefore
`unresolved`, rather than silently falling back to the document. Explicit
anchors on nodes that do not become Lens entries are still recognized as valid
internal destinations.

`locate` normally ranks exact names, headings, body phrases, and unordered token
matches. Text comparisons fold accents, and supported Sphinx search languages
also compare stemmed terms. `--regex` interprets the query as a case-insensitive
Python regular expression and keeps literal matching rules. Repeat `--kind` to
select documents, sections, or objects; use `--domain py` to restrict domain
objects. Repeat `--under PATH` to search multiple document subtrees. `--json`
returns structured results.

The score is explainable:

| Match | Score | Ranking factors |
| --- | ---: | --- |
| Exact name | `1.0` | Highest priority |
| Phrase in heading | `0.9` | Heading match |
| Phrase in body | `0.55`–`0.70` | Body length |
| Unordered terms | Up to `0.69` | Term coverage, heading coverage, and body length |

Regex results use the same exact-name, heading, and body tiers.

`inspect` returns an entry as JSON with its physical `location`. Pass
`--no-text` to omit the full text when only structural metadata is needed.

```bash
sphinx-lens locate "database transactions" --under topics -i docs/_build/lens
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
metadata = lens.document_metadata(entry.ref)
children = lens.children("guide/network")
outgoing = lens.references(entry.ref)
both_directions = lens.linked(entry.ref)
```

`Entry.location` maps domain objects back to their physical `document#anchor`.
Links use physical locations so incoming references to a section and to an
object at the same Sphinx anchor can be combined.

## Extracted text

Lens stores each entry's own text as a normalized plain-text string. Most docutils
markup is flattened by `astext()`, including code blocks, tables, and admonitions.
Images are the deliberate exception: each image is preserved as a Markdown-style
reference so its destination remains available to consumers:

| Sphinx node | Extracted representation |
| --- | --- |
| Image with alternative text | `![Setup diagram](images/setup.svg)` |
| Image without alternative text | `![](images/logo.svg)` |

The image URI and alternative text are taken from the doctree after Sphinx has
resolved the document. Lens does not copy or embed the image asset in the index.

## Index model

The version 4 JSON document contains the following fields:

The index version tracks serialized-schema compatibility, not project maturity.
Even while Lens is alpha, the version is incremented when index fields or their
required interpretation change. `Lens.open()` rejects a mismatched version
instead of silently reading an incompatible artifact; rebuild the index after an
upgrade that changes the version.

- `source`: the source directory relative to the artifact, or `null` when the
  artifact was written outside the source tree and no relative path would
  survive being moved.
- `metadata`: Sphinx version, configured extensions, UTC build time, Git commit,
  configured language, and a SHA-256 hash for each source document.
- `documents`: a map from document name to its Sphinx title and file-wide
  metadata. Values are kept as Sphinx recorded them; MyST JSON-encodes
  non-scalar frontmatter values.
- `no_search`: document names omitted from `locate` by metadata or configuration.
- `entries`: documents, sections, and domain objects with normalized text,
  parent relationships, and an `order` recording each entry's position in its
  document.
- `links`: internal, external, and unresolved directed references.

RST has no YAML frontmatter block. Use a leading docinfo field list instead;
Sphinx records custom RST fields as strings:

```rst
:audience: developers
:keywords: search, navigation
:sources: docs, api

Invoicing
=========

The canonical guide.
```

These fields are docinfo, not hidden frontmatter, and a Sphinx builder or theme
may render them. Lens does not define a custom directive for hidden RST
metadata; it exposes the metadata Sphinx already records. Projects that need
hidden or structured RST metadata should use a Sphinx extension or MyST
frontmatter instead.

MyST can represent structured values in frontmatter, and Lens stores those
values as JSON strings. RST fields remain strings, so applications that need
structured RST metadata should choose a delimiter or encode JSON explicitly.

A link counts as resolved for reporting when its kind is `internal` or `external`.
An internal link is resolved only when its document and, if present, its anchor
are known locations in the index. An `unresolved` link has no verified local
destination. Classifying an absolute URL as `external` does not check whether
the remote URL is reachable.

`Lens.document_metadata(target)` resolves a document, section, or domain object
and returns the metadata for its containing document. `Lens.open()` rejects
older index versions with a rebuild message and warns when available local
sources no longer match their hashes. An index with a `null` source emits a
`StaleIndexWarning` explaining that the check cannot run; missing sources do not
prevent an artifact from loading.

Documents, sections, and objects store only their own normalized text. `read`
reconstructs a scope by composing its descendants in source order, and
`children` returns them the same way, so a composed page reads top to bottom
rather than alphabetically. Markup distinctions such as code blocks and tables
are not preserved.

A document's own text is its title and the prose before its first subheading.
Sphinx titles a document from its single top-level section, and that section is
addressed as the document itself rather than as `document#anchor`, so its prose
belongs to the document entry and is stored there exactly once.

The index is a portable intermediate representation and nothing more: one JSON
file, readable without Sphinx, a database, or a model. `locate` is a reference
finder, not semantic similarity search.
