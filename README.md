# Sphinx Lens

[![CI](https://github.com/mgaitan/sphinx-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/mgaitan/sphinx-lens/actions/workflows/ci.yml)
[![docs](https://img.shields.io/badge/docs-blue.svg?style=flat)](https://mgaitan.github.io/sphinx-lens/)
[![pypi version](https://img.shields.io/pypi/v/sphinx-lens.svg)](https://pypi.org/project/sphinx-lens/)
[![Changelog](https://img.shields.io/github/v/release/mgaitan/sphinx-lens?include_prereleases&label=changelog)](https://github.com/mgaitan/sphinx-lens/releases)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/mgaitan/sphinx-lens/actions/workflows/ci.yml)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![License](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](https://github.com/mgaitan/sphinx-lens/blob/main/LICENSE)


Structure-aware indexing and precise navigation for Sphinx documentation.

Sphinx Lens gives coding agents a small, portable view of a documentation
project: stable Sphinx references, scoped text, hierarchy, and the compiled link
graph. Its search command finds those references; it is lexical, not an
embedding or LLM search engine.

## Quick Start

Install Sphinx Lens in the same environment as the documentation and build the
index like any other Sphinx artifact:

```bash
sphinx-build -b lens docs/ docs/_build/lens/
sphinx-lens locate "connection timeout" --index docs/_build/lens/
sphinx-lens inspect py:class:example.Client --index docs/_build/lens/
sphinx-lens read guide/network#timeouts --index docs/_build/lens/
sphinx-lens links guide/network#timeouts --index docs/_build/lens/
```

The `lens` builder is discovered through Sphinx's builder entry point; no
`conf.py` change is required. It loads the project's formats, extensions, and
domains, then writes `docs/_build/lens/index.json`. Projects can expose this as
`make lens`; `sphinx-lens build docs/` is the equivalent convenience command.

Sphinx executes `conf.py` during every build. Only index projects you trust, and
run the command in the project's documentation environment so MyST, autodoc,
themes, and project-specific extensions are importable.

Install the bundled agent skill with
[Library Skills](https://github.com/tiangolo/library-skills):

```bash
uvx library-skills install --skill sphinx-lens --yes
```

See the [design explanation](docs/design.md) for how Lens differs from
`objects.inv`, `searchindex.js`, and Sphinx doctrees.

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

## Documentation

- Docs follow [Diataxis](https://diataxis.fr/).
- Start at `docs/index.md` and read:
  - `docs/getting_started.md` (tutorial),
  - `docs/development_workflow.md` (how-to),
  - `docs/configuration.md` (reference),
  - `docs/about_the_docs.md` (explanation and design rationale).
