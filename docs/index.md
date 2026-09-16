# Sphinx Lens

[![ci](https://github.com/mgaitan/sphinx-lens/workflows/ci/badge.svg)](https://github.com/mgaitan/sphinx-lens/actions?query=workflow%3Aci)
[![docs](https://img.shields.io/badge/docs-blue.svg?style=flat)](https://mgaitan.github.io/sphinx-lens/)
[![pypi version](https://img.shields.io/pypi/v/sphinx-lens.svg)](https://pypi.org/project/sphinx-lens/)
[![Changelog](https://img.shields.io/github/v/release/mgaitan/sphinx-lens?include_prereleases&label=changelog)](https://github.com/mgaitan/sphinx-lens/releases)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/mgaitan/sphinx-lens/actions/workflows/ci.yml)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![License](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](https://github.com/mgaitan/sphinx-lens/blob/main/LICENSE)

**Structure-aware indexing and precise navigation for Sphinx documentation.**

## The problem

Any documentation project large enough to be worth searching is too large to
read. Asking it one specific question usually leaves two options, and both are
bad: grep the sources and get the word without the scope that explains it, or
read whole files and bury the relevant paragraph under hundreds of others. What
neither approach has is structure.

Take a concrete case. You want to know whether `atomic()` rolls back to a
savepoint or to the start of the outermost block. The answer is one paragraph
somewhere in Django's documentation, which is 674 source files and about 10 MB
of prose.

Grep for `atomic` and you get several hundred hits across tutorials, release
notes, and API tables, with no way to tell which one is the definition. Feed the
likely files to a model instead and you spend tens of thousands of tokens on
prose about connection pooling and test runners to reach three sentences.

Sphinx has just finished compiling that same project and knows the answer's
address. It knows `django.db.transaction.atomic` is a documented function, which
section documents it, that the section ends where the next heading begins, and
which other pages cross-reference it. It parsed RST and MyST, ran autodoc and
the project's own extensions, built a domain inventory of every class, function,
and glossary term, and resolved every reference to produce that knowledge. Then
it renders HTML and throws all of it away.

## What Sphinx Lens does

Sphinx Lens is a Sphinx builder that keeps that knowledge. Instead of HTML it
writes a single JSON index of everything the compiled environment already knows:
documents, sections, and domain objects, each with a stable reference and its
own scoped text, plus the full directed graph of cross-references between them.

Building it is a normal Sphinx build. Most projects need no configuration, and
search exclusions can be declared when generated pages should stay navigable:

```bash
sphinx-build -b lens docs/ docs/_build/lens/
```

From then on the questions are cheap. Staying with Django as the example, find
the reference:

```console
$ sphinx-lens locate "database transactions" -i /tmp/django-lens --limit 3
1.00  std:label:topics/db/transactions:database transactions
1.00  topics/db/transactions
0.90  std:label:topics/db/transactions:managing database transactions
```

Read that scope on its own:

```console
$ sphinx-lens read py:function:django.db.transaction.atomic -i /tmp/django-lens
```

Or ask what the rest of the documentation says about it:

```console
$ sphinx-lens links py:class:django.db.models.Model -i /tmp/django-lens
```

The unit of retrieval throughout is a documented scope: what the author wrote as
one idea, addressed by the name the project gave it. That is the whole idea, and
it applies to a ten-page internal handbook as much as to Django.

## Scope and limits

`locate` is lexical. It ranks exact names, headings, phrases, and token matches,
and it accepts regular expressions. It has no notion of embedding similarity and
will not answer a question phrased as a question. Its job is to find the right
reference quickly; reading and traversing are what the index is for.

The scope of the project stops at the index. It has one runtime dependency,
Sphinx itself, and it writes a file you can commit, publish next to your HTML,
or pipe through `jq`. Retrieval frameworks, agent runtimes, and servers are all
things that can be built on top of it.

## Where to start

New here? [Getting started](getting_started.md) builds an index and queries it
in a few minutes. If you would rather see whether the idea holds up first,
[How it works](design.md) explains the model,
[Index a narrative corpus](narrative_corpus.md) covers article-based knowledge
bases, and [Real-world corpora](corpus_evaluation.md) reports what it does to
Django and CPython.

```{toctree}
:maxdepth: 2

getting_started.md
reference.md
design.md
narrative_corpus.md
corpus_evaluation.md
configuration.md
development_workflow.md
about_the_docs.md
../CONTRIBUTING.md
../CODE_OF_CONDUCT.md
```
