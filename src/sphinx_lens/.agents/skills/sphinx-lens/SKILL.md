---
name: sphinx-lens
description: Use when an agent needs to answer questions from a Sphinx documentation project, locate concepts or API objects, inspect a document/section/object, follow cross-references, or avoid reading an entire documentation tree. Trigger for requests to explore compiled Sphinx structure with sphinx-lens, including RST, MyST Markdown, autodoc, custom domains, and large documentation corpora. Do not use for editing prose or building ordinary HTML unless structured navigation is part of the task.
---

# Sphinx Lens

Use the compiled Sphinx structure as the retrieval layer. Prefer narrow semantic
results over scanning or loading entire source trees.

## Workflow

1. Find an existing index. Check `docs/_build/lens/index.json` or the path the user provides.
2. If it is absent or stale, prefer the project's `make lens` target. Otherwise
   run `sphinx-lens build docs` inside the project's documentation environment;
   this writes `docs/_build/lens/index.json`.
3. Identify the corpus shape before choosing a query: API corpora expose domain
   objects, while narrative corpora may contain only documents and sections.
4. Start with `sphinx-lens locate` using a short natural-language phrase. For a
   narrative corpus, use content words from the procedure rather than a complete
   question; add repeatable `--under PATH` values when the source tree provides a
   useful product, module, or country boundary.
5. Use `--regex`, `--kind`, or `--domain` only when the initial results are too
   broad or the task names a structural constraint.
6. Use the returned canonical reference with `inspect`, `read`, or `links`.
7. Read the smallest useful scope. Follow links only when the current entry does
   not answer the question, or when it explicitly depends on another procedure.
8. Cite the physical `location` from `inspect` or the document reference used for
   the answer. Name the canonical references so another agent can reproduce the
   path.

## Query Selection

- Use normal `locate` for concepts and phrases. It ranks exact names, headings,
  body phrases, and token matches.
- In a corpus with accents or inflection, query with the corpus language in mind:
  Lens folds accents and uses the configured Sphinx stemmer when that language is
  supported. Unsupported languages get accent folding but no stemming.
- Use `--under PATH` to keep a narrative search inside one or more document
  subtrees. This can provide useful scope even when the corpus has no domain
  objects or complete toctree.
- Use regex for naming families, optional words, anchors, or signatures.
- Filter with `--kind object --domain py` for API lookup.
- Use `links` for dependency, related-topic, and provenance questions.
- Use `--json` with `jq` for projection, grouping, or custom predicates.
- Use `rg` directly on the JSON for quick reconnaissance when ranking and
  semantic filtering do not matter.

Do not treat unresolved links as missing source content. They may be contextual
domain references, intersphinx targets, or stale anchors outside the local
 inventory. If `read` includes an image token with empty or placeholder alt text,
 report that the answer depends on an undescribed image rather than guessing what
 the image contains.

Read [querying.md](references/querying.md) when constructing regex, `jq`, Python
API, or builder commands.
