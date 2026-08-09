# About these docs

Conventions for anyone writing documentation in this repository. If you are here
to *use* Sphinx Lens, you want [Getting started](getting_started.md) instead.

## Documentation ships with the change

Docs and implementation live in the same repository and evolve in the same pull
request. A behavioral change without a documentation change is an incomplete
change, in the same way a behavioral change without a test is.

## Broken docs break the build

`make docs` runs Sphinx with warnings as errors, so a dead cross-reference, a
malformed directive, or an orphaned page fails CI rather than shipping quietly.

## Run the examples, do not retype them

Hand-written command output rots. Where a chapter shows a command, prefer
[richterm](https://github.com/mgaitan/richterm), which runs it during the docs
build, and [sphinxcontrib-mermaid](https://github.com/mgaitan/sphinxcontrib-mermaid)
for diagrams that live as text.

Numbers recorded from long or expensive runs, such as the corpus measurements,
are the exception. Those are transcribed on purpose, with the commit they came
from, so a reader can re-verify them deliberately.

## Order the chapters as a reading path

The chapter order in the sidebar is a reading order: get it running, look
something up, understand why it is built this way, see what it does under load,
contribute. [Diataxis](https://diataxis.fr/) informed that shape, giving a
tutorial, reference material, and explanation each one job to do. It stays a
writing tool: the reader should never have to know about it. Do not label
chapters with their Diataxis mode, and do not split the table of contents into
one group per mode.

Keep environment variable definitions in [Environment variables](configuration.md)
using the `glossary` directive, and refer to them with `{term}` (for example
{term}`PYTHONPATH`) so the definition has exactly one home.

## Publishing is automated

`gh:.github/workflows/cd.yml` deploys to GitHub Pages: release and manual runs
publish the canonical site, and pull requests that touch docs publish a preview
under `https://mgaitan.github.io/sphinx-lens/_preview/pr-<PR_NUMBER>/`.

Manual dispatch through the `gh` CLI usually authenticates with {term}`GH_TOKEN`;
the workflow internals use {term}`GITHUB_TOKEN`.

These conventions come from the repository template; the reasoning behind them
is written up in
[Opinionated Python project scaffolding](https://mgaitan.github.io/en/posts/opinionated-python-project-scaffolding/).
