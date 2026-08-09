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

Django's documentation is 674 source files and about 10 MB of prose. When a
coding agent needs to know how `atomic()` interacts with savepoints, it has two
bad options. It can grep the sources, which finds the word but not the scope
that explains it, and returns fragments cut at arbitrary line boundaries. Or it
can read whole files into its context window, which is expensive, imprecise, and
tends to bury the relevant paragraph under thousands of irrelevant ones.

Neither option knows that `django.db.transaction.atomic` is a *thing*, that it
lives in a specific section, that eleven other pages point at it, or that the
paragraph explaining it ends where the next heading begins.

Sphinx does know all of that. It parses RST and MyST, expands autodoc, runs the
project's own extensions, builds a domain inventory of every documented class,
function, and glossary term, and resolves every cross-reference. Then it renders
HTML and throws the knowledge away.

## What Sphinx Lens does

Sphinx Lens is a Sphinx builder that keeps that knowledge. Instead of HTML it
writes a single JSON index of everything the compiled environment already knows:
documents, sections, and domain objects, each with a stable reference and its
own scoped text, plus the full directed graph of cross-references between them.

Building it is a normal Sphinx build, so it costs one command and no
configuration:

```bash
sphinx-build -b lens docs/ docs/_build/lens/
```

From then on, the questions are cheap. Find the reference:

```console
$ sphinx-lens locate "database transactions" -i docs/_build/lens --limit 3
1.00  std:label:topics/db/transactions:database transactions
1.00  topics/db/transactions
0.90  std:label:topics/db/transactions:managing database transactions
```

Read exactly that scope and nothing else:

```console
$ sphinx-lens read py:function:django.db.transaction.atomic -i docs/_build/lens
```

Or ask what the rest of the documentation says about it:

```console
$ sphinx-lens links py:class:django.db.models.Model -i docs/_build/lens
```

The unit of retrieval is a documented scope, not a file and not a line range.
That is the whole idea.

## What it is not

`locate` is lexical. It ranks exact names, headings, phrases, and token matches,
and it accepts regular expressions, but it does not do embedding similarity and
will not answer a question phrased as a question. It is a way to find the right
reference quickly; reading and traversing are what the index is really for.

Sphinx Lens is also not a retrieval framework, an agent runtime, or a second
Markdown parser. It has one runtime dependency, Sphinx itself, and it writes a
file you can commit, publish next to your HTML, or pipe through `jq`.

## Where to start

New here? [Getting started](getting_started.md) builds an index and queries it
in a few minutes. If you would rather see whether the idea holds up first,
[How it works](design.md) explains the model and
[Real-world corpora](corpus_evaluation.md) reports what it does to Django and
CPython.

```{toctree}
:maxdepth: 2

getting_started.md
reference.md
design.md
corpus_evaluation.md
configuration.md
development_workflow.md
about_the_docs.md
../CONTRIBUTING.md
../CODE_OF_CONDUCT.md
```
