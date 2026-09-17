# Sphinx Lens

[![CI](https://github.com/mgaitan/sphinx-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/mgaitan/sphinx-lens/actions/workflows/ci.yml)
[![docs](https://img.shields.io/badge/docs-blue.svg?style=flat)](https://mgaitan.github.io/sphinx-lens/)
[![pypi version](https://img.shields.io/pypi/v/sphinx-lens.svg)](https://pypi.org/project/sphinx-lens/)
[![Changelog](https://img.shields.io/github/v/release/mgaitan/sphinx-lens?include_prereleases&label=changelog)](https://github.com/mgaitan/sphinx-lens/releases)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/mgaitan/sphinx-lens/actions/workflows/ci.yml)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![License](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](https://github.com/mgaitan/sphinx-lens/blob/main/LICENSE)


**Structure-aware indexing and precise navigation for Sphinx documentation.**

Sphinx knows things about your documentation that nothing downstream gets to
use: which text belongs to which section, that `django.db.transaction.atomic` is
a documented object with a canonical name, and where every cross-reference
points. Then it renders HTML and throws that away.

Sphinx Lens is a Sphinx builder that writes it down instead. The output is a
single JSON index of documents, sections, and domain objects, each with a stable
reference and its own scoped text, plus the compiled link graph between them.
Coding agents get to read one precise scope instead of grepping a source tree.

Each scope remains separately addressable. Consumers can retrieve the relevant
part of the documentation without loading a whole-site text export or recovering
structure from generated HTML.

## Quick start

Install Sphinx Lens in the same environment as your documentation and build the
index like any other Sphinx artifact:

```bash
sphinx-build -b lens docs/ docs/_build/lens/
sphinx-lens locate "connection timeout"
sphinx-lens inspect py:class:example.Client
sphinx-lens read guide/network#timeouts
sphinx-lens links guide/network#timeouts
```

The `lens` builder is discovered through Sphinx's builder entry point; no
`conf.py` change is required. It loads the project's formats, extensions, and
domains, then writes `docs/_build/lens/index.json`. Query commands discover that
index from the repository root or anywhere inside the Sphinx source tree.
Projects can expose the build as `make lens`; `sphinx-lens build docs/` is the
equivalent convenience command.

Sphinx executes `conf.py` during every build. Only index projects you trust, and
run the command in the project's documentation environment so MyST, autodoc,
themes, and project-specific extensions are importable.

Install the bundled agent skill with
[Library Skills](https://library-skills.io/):

```bash
uvx library-skills install --skill sphinx-lens --yes
```

`locate` is lexical. It finds the right reference so that `read` and `links` can
do the real work; embedding similarity is out of scope.

Full documentation is at <https://mgaitan.github.io/sphinx-lens/>. Start with
[Getting started](docs/getting_started.md), or read
[How it works](docs/design.md) for why this is a separate artifact rather than a
reuse of `objects.inv`, `searchindex.js`, or Sphinx doctrees.

## Development

- Install dependencies with `uv sync`.
- New dependency releases are delayed by one week via `uv` cooldown (`[tool.uv].exclude-newer = "1 week"`), with per-package overrides when required (for example, `ty`).
- Make targets and GitHub Actions enable uv's malware check against known malicious-package advisories.
- Install [`prek`](https://github.com/j178/prek) as an external tool:

```bash
uv tool install prek
```

- Install git hooks with `prek`:

```bash
prek install
```

- Run the local QA bundle with `prek`:

```bash
prek run --all-files
```

- PRs with documentation changes publish a docs preview at:

```text
https://mgaitan.github.io/sphinx-lens/_preview/pr-<PR_NUMBER>/
```

- Build this project's own index with `make lens`, and the docs with `make docs`.
