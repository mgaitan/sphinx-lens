# Index a narrative corpus

Sphinx Lens also works when a documentation tree is a collection of articles
rather than an API reference. This matters for manuals, runbooks, and other
prose-heavy documentation: the useful unit is usually a paragraph or a section,
and source paths often provide useful retrieval context.

This chapter uses a reproducible run against the public
[MyST-Parser documentation](https://github.com/executablebooks/MyST-Parser/tree/723cffcf84213f0cb58695b27eec9ad72052b53a).
The pinned commit is `723cffcf84213f0cb58695b27eec9ad72052b53a`. Its 28 Markdown
documents cover getting started, syntax, reference material, FAQs, and project
development. The corpus contains both narrative sections and 73 standard
objects, so it also shows how article-oriented retrieval works when a corpus is
not limited to one object domain.

## Build the corpus without changing its sources

Clone the public repository and check out the recorded commit:

```bash
git clone https://github.com/executablebooks/MyST-Parser /tmp/myst-parser-public
git -C /tmp/myst-parser-public checkout 723cffcf84213f0cb58695b27eec9ad72052b53a
```

Keep the Sphinx configuration outside the source tree when the exported content
must remain untouched. The configuration used for the recorded run was:

```python
project = "MyST Parser documentation"
root_doc = "index"
language = "en"
extensions = ["myst_parser"]
exclude_patterns = ["_build"]
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "dollarmath",
    "fieldlist",
    "tasklist",
]
```

Build the index with the configuration and doctree directories outside the
corpus:

```bash
uv run sphinx-lens build /tmp/myst-parser-public/docs \
  --output /tmp/myst-lens-out \
  --conf-dir /tmp/myst-lens-conf \
  --doctree-dir /tmp/myst-lens-doctrees
```

The output is one `index.json` file. Sphinx reads the source tree, but Lens does
not need to modify it to index the documents.

## A complete toctree is optional

Lens extracts documents from Sphinx's `env.found_docs`, not only from documents
reachable through a `toctree`. The MyST-Parser documentation has root and nested
toctrees, but the same extraction rule applies to a corpus with incomplete
navigation: documents that Sphinx discovers remain available to `resolve`,
`read`, and `locate`.

The recorded build emitted 203 warnings. Review those warnings separately from
the index output; a navigation warning describes a Sphinx documentation issue,
while it does not by itself show that Lens failed to extract a document. If a
project intentionally leaves some documents outside its navigation tree, the
external configuration can suppress the corresponding Sphinx warning:

```python
suppress_warnings = ["toc.not_included"]
```

Do not add a synthetic toctree only to make a warning disappear. A toctree adds
navigation links, but it does not create parent relationships between separate
document entries in the Lens index.

## Search in the corpus language

`locate` is lexical search. It compares titles, references, headings, and the
text stored for each scope. It folds accents, and when the Sphinx configuration
records a supported search language, Lens also compares stemmed terms. The
recorded corpus uses English, so the search configuration matches its source
text:

```bash
sphinx-lens locate "cross-referencing" \
  --index /tmp/myst-lens-out --limit 5
```

Use content words instead of a complete support question. A question phrased
with vocabulary absent from an article cannot be recovered by lexical search
alone. Read the narrowest returned section, then follow its links when the
procedure depends on another scope. `read` composes descendants in source
order, which preserves the article flow without sending the whole corpus to a
consumer.

## Use document paths as a taxonomy

Metadata can describe a document, but a directory prefix is often a stable query
boundary for documentation organized by topic. Use `--under` to restrict a
query to one or more source subtrees:

```bash
sphinx-lens locate "cross-referencing" \
  --under syntax --index /tmp/myst-lens-out
```

Repeated `--under` values form a union. The filter composes with `--kind`,
`--domain`, and `--regex`. This is useful even when a corpus has few domain
objects because documents and sections remain addressable by their source paths.

## Measured cost and limits

The recorded run used Sphinx Lens commit `a7053be` with Sphinx 9.1.0. It produced
28 document entries, 239 section entries, and 73 object entries. The index
contained 541 links: 184 internal, 349 external, and 8 unresolved. The measured
resolution rate was 98.5%, and the JSON artifact was 419,972 bytes (about
410 KB).

`unresolved` means that Lens could not verify a local target or could not resolve
the reference. This classification does not test whether an external URL is
reachable. The CLI parses the complete JSON index on every process start, so
repeated queries should account for index loading as well as search work.

A narrative corpus benefits from the same retrieval loop as an API corpus: find
a reference, read its narrowest scope, and traverse only the links needed to
understand it. The difference is where the structure comes from. Domain objects
may be sparse or absent, so source paths, headings, and the document metadata
supplied by Sphinx carry more of the retrieval context.
