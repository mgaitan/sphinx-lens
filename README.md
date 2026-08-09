# Sphinx Lens

[![CI](https://github.com/mgaitan/sphinx-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/mgaitan/sphinx-lens/actions/workflows/ci.yml)
[![docs](https://img.shields.io/badge/docs-blue.svg?style=flat)](https://mgaitan.github.io/sphinx-lens/)
[![pypi version](https://img.shields.io/pypi/v/sphinx-lens.svg)](https://pypi.org/project/sphinx-lens/)
[![Changelog](https://img.shields.io/github/v/release/mgaitan/sphinx-lens?include_prereleases&label=changelog)](https://github.com/mgaitan/sphinx-lens/releases)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/mgaitan/sphinx-lens/actions/workflows/ci.yml)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![License](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](https://github.com/mgaitan/sphinx-lens/blob/main/LICENSE)


Semantic extraction and navigation for Sphinx documentation

## Quick Start

Build a portable semantic index from any Sphinx source tree:

```bash
uvx sphinx-lens build docs/
uvx sphinx-lens locate "connection timeout" --index docs/
uvx sphinx-lens inspect py:class:example.Client --index docs/
uvx sphinx-lens read guide/network#timeouts --index docs/
uvx sphinx-lens links guide/network#timeouts --index docs/
```

`build` lets Sphinx load the project's formats, extensions, and domains, then
writes `docs/.sphinx-lens/index.json`. The other commands query that JSON artifact
without rebuilding the documentation.

To install the tool permanently:

```bash
uv tool install sphinx-lens
```

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
