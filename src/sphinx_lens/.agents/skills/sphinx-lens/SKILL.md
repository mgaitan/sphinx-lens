---
name: sphinx-lens
description: Use when an agent needs to answer questions from a Sphinx documentation project, locate concepts or API objects, inspect a document/section/object, follow cross-references, or avoid reading an entire documentation tree. Trigger for requests to explore compiled Sphinx structure with sphinx-lens, including RST, MyST Markdown, autodoc, custom domains, and large documentation corpora. Do not use for editing prose or building ordinary HTML unless structured navigation is part of the task.
---

# Sphinx Lens

Use the compiled Sphinx structure as the retrieval layer. Prefer narrow semantic
results over scanning or loading entire source trees.

## Workflow

1. Read the project's agent guidance first. It may declare a versioned index or
   a project-specific build command.
2. Run query commands from the repository or Sphinx source tree. Lens discovers
   `_build/lens/index.json` next to a nearby `conf.py`; use `-i` only when project
   guidance names a nonstandard artifact.
3. Query an existing index directly. Do not rebuild ordinary HTML or regenerate a
   current index merely to answer a question.
4. Rebuild when the index is absent, Lens warns that sources changed, or project
   state indicates that the artifact may be incomplete. The warning cannot detect
   newly added source files, changes to `conf.py`, changed autodoc inputs, or
   sources unavailable beside a portable artifact. A missing result for content
   known to be new or regenerated is also a reason to rebuild.
5. To rebuild, use a project-specific command only when the repository documents
   one. Otherwise run `sphinx-lens build`; it discovers the applicable `conf.py`
   and writes beside it at `_build/lens/index.json`. Pass the Sphinx source
   directory explicitly only when discovery reports multiple projects.
6. Identify the corpus shape before choosing a query: API corpora expose domain
   objects, while narrative corpora may contain only documents and sections.
7. Start with `sphinx-lens locate` using a short natural-language phrase. For a
   narrative corpus, use content words from the procedure rather than a complete
   question; add repeatable `--under PATH` values when the source tree provides a
   useful product, module, or country boundary.
8. Use `--regex`, `--kind`, or `--domain` only when the initial results are too
   broad or the task names a structural constraint.
9. Use the returned canonical reference with `inspect`, `read`, or `links`.
10. Read the smallest useful scope. Follow links only when the current entry does
   not answer the question, or when it explicitly depends on another procedure.
11. Cite the physical `location` from `inspect` or the document reference used for
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
