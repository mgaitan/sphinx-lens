# Sphinx Lens

[![ci](https://github.com/mgaitan/sphinx-lens/workflows/ci/badge.svg)](https://github.com/mgaitan/sphinx-lens/actions?query=workflow%3Aci)
[![docs](https://img.shields.io/badge/docs-blue.svg?style=flat)](https://mgaitan.github.io/sphinx-lens/)
[![pypi version](https://img.shields.io/pypi/v/sphinx-lens.svg)](https://pypi.org/project/sphinx-lens/)
[![Changelog](https://img.shields.io/github/v/release/mgaitan/sphinx-lens?include_prereleases&label=changelog)](https://github.com/mgaitan/sphinx-lens/releases)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/mgaitan/sphinx-lens/actions/workflows/ci.yml)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![License](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](https://github.com/mgaitan/sphinx-lens/blob/main/LICENSE)


Structure-aware indexing and precise navigation for Sphinx documentation.

Sphinx Lens compiles stable references, scoped text, hierarchy, and links for
coding agents. Its lexical search locates a reference; it does not claim
embedding-based semantic similarity.

## Quick Start

Run from the project's environment so its Sphinx extensions are available:

```bash
uv run --group docs sphinx-lens --help
```

When running from source, we use {term}`PYTHONPATH` in docs examples so the local package is importable without an install step.

```{richterm} env PYTHONPATH=../src uv run -m sphinx_lens --help
:hide-command: true
```

The native `lens` builder writes `_build/lens/index.json` alongside other Sphinx
artifacts. See [Getting Started](getting_started.md) for the complete workflow.

## Documentation Map (Diataxis)

This project follows the [Diataxis](https://diataxis.fr/) framework:

- Tutorials: learning-oriented, step-by-step.
- How-to guides: goal-oriented operational procedures.
- Reference: factual, lookup-first technical details.
- Explanation: context, rationale, and design choices.


```{toctree}
:maxdepth: 2
:caption: Tutorials

getting_started.md
```

```{toctree}
:maxdepth: 2
:caption: How-to Guides

development_workflow.md
```

```{toctree}
:maxdepth: 2
:caption: Reference

configuration.md
reference.md
```

```{toctree}
:maxdepth: 2
:caption: Explanation

about_the_docs.md
design.md
corpus_evaluation.md
```

```{toctree}
:maxdepth: 2
:caption: Project Policies

../CONTRIBUTING.md
../CODE_OF_CONDUCT.md
```
