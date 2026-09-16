# Index a narrative corpus

Sphinx Lens also works when a documentation tree is a collection of articles
rather than an API reference. This matters for support manuals, runbooks, and
knowledge bases: the useful unit is usually a paragraph or a section, and the
source files may not have domain objects or a complete table of contents.

This chapter uses a recorded run against the Fierro knowledge base as a concrete
example. The corpus contains 977 Markdown files: 795 articles with frontmatter
and 182 generated `index.md` files. It is mostly Spanish, so the language notes
below describe that corpus rather than the English examples used elsewhere in
this documentation.

## Build the corpus without changing its sources

Keep the Sphinx configuration outside an exported content tree when the export
must remain untouched. A minimal configuration for the recorded run enabled
MyST, selected `index` as the root document, excluded assets and `.ok/`, and
enabled colon fences:

```python
extensions = ["myst_parser"]
root_doc = "index"
exclude_patterns = ["**/assets/**", ".ok/**", "_build/**"]
language = "es"
myst_enable_extensions = ["colon_fence"]
```

Build it with the native Sphinx command:

```bash
sphinx-build -b lens -c /tmp/kb-lens-conf \
  ~/lambda/kb/knowledge /tmp/kb-lens-out
```

The output is one `index.json` file. The source tree is read by Sphinx, but Lens
does not need to modify it to index the documents.

## A toctree is optional

Lens extracts documents from Sphinx's `env.found_docs`, not only from documents
reachable through a `toctree`. A corpus can therefore contain articles that are
not listed in navigation and still make them available to `resolve`, `read`, and
`locate`.

Sphinx reports `toc.not_included` for documents that no toctree includes. In the
recorded run, 976 of 1,553 build warnings had this cause. These warnings describe
a navigation gap, not an indexing failure. If the project intentionally has no
complete toctree, suppress that warning in the external configuration:

```python
suppress_warnings = ["toc.not_included"]
```

The remaining warnings then identify content problems that need attention rather
than expected consequences of the corpus layout. Do not add a synthetic toctree
only to make the warning disappear: a toctree contributes navigation links, but
it does not create parent relationships between separate document entries in the
Lens index.

## Search in the corpus language

`locate` is lexical search. It compares titles, references, headings, and the
text stored for each scope. It folds accents, so `deposito` and `depósito` are
compared consistently. When the Sphinx configuration records a supported search
language, Lens also compares stemmed terms; this lets inflected forms such as
`copio` and `copiar` match when the configured language provides a stemmer.
Unsupported languages still get accent folding, but no stemming.

Search with content words instead of a complete support question. For example,
use the distinctive terms from a procedure:

```bash
sphinx-lens locate "connection timeout" \
  --index /tmp/kb-lens-out --limit 5
```

A question phrased with vocabulary absent from the article cannot be recovered by
lexical search alone. Read the narrowest returned section, then follow its links
when the procedure depends on another scope. `read` composes descendants in
source order, which preserves the article flow without sending the whole corpus
to a consumer.

## Use document paths as a taxonomy

Metadata can describe a document, but a directory prefix is often a more stable
query boundary for an exported knowledge base. Use `--under` when the corpus
already groups articles by product area, module, or country:

```bash
sphinx-lens locate "connection timeout" \
  --under guides --under reference \
  --index /tmp/kb-lens-out
```

Repeated `--under` values form a union. The filter composes with `--kind`,
`--domain`, and `--regex`. This is useful even when the corpus has zero domain
objects because documents and sections remain addressable by their source paths.

## Measured cost and limits

The recorded run used Sphinx Lens commit `a7053be`. The Fierro run produced 977 document entries, 1,771 section entries, and no
domain objects. It contained 2,567 links: 1,752 internal and 815 external. The
index was 3.4 MB. A cold CLI query took 0.33 seconds and used 50 MB of resident
memory on the machine that recorded the measurement. At this size, the JSON
artifact is small enough for ordinary build and query workflows; repeated CLI
invocations still parse the complete file on every process start.

Extraction quality remains separate from index size. Before the document-lede
fix, all 977 document entries had empty own text and 420 documents had no text
anywhere in the index. The fix makes the prose before a document's first
subheading available. Images are retained as Markdown-style `![alt](uri)` text,
but Lens does not describe an image whose source has no useful alternative text.
A consumer should report that dependency rather than infer what a screenshot
contains.

A narrative corpus benefits from the same retrieval loop as an API corpus: find
a reference, read its narrowest scope, and traverse only the links needed to
understand it. The difference is where the structure comes from. Domain names
may be absent, so source paths, headings, and the document metadata supplied by
Sphinx carry more of the retrieval context.
