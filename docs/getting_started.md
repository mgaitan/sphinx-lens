# Getting Started (Tutorial)

This tutorial builds and explores a structure-aware index for a Sphinx project.

## 1. Create the environment

From the project root:

```bash
uv sync
```

This resolves dependencies and creates the local virtual environment.

## 2. Build the index

Install Sphinx Lens in the same environment as the project's documentation
dependencies, then invoke its native builder:

```bash
uv run sphinx-build -b lens docs/ docs/_build/lens/
```

Projects can expose that command as `make lens`. Sphinx discovers the builder
from the installed package; `conf.py` does not need to list `sphinx_lens`. The
output is the normal Sphinx artifact `docs/_build/lens/index.json`. The command
`uv run sphinx-lens build docs/` is a convenience wrapper for the same build.

Both forms execute the project's `conf.py`. Use a trusted checkout and the
project's own environment so all configured extensions and imports are present.

## 3. Explore the documentation

Search across document titles, section text, and domain objects:

```bash
uv run sphinx-lens locate "design decisions" --index docs/_build/lens/
```

Use a result reference to read only that structural scope or inspect its metadata:

```bash
uv run sphinx-lens read about_the_docs#design-decisions-captured-here --index docs/_build/lens/
uv run sphinx-lens inspect about_the_docs#design-decisions-captured-here --index docs/_build/lens/
uv run sphinx-lens links about_the_docs#design-decisions-captured-here --index docs/_build/lens/
```

Domain objects have stable references such as `py:class:package.Client` and
`std:term:PYTHONPATH`.

## 4. Use the Python API

```python
from sphinx_lens import Lens

lens = Lens.open("docs/_build/lens/")
section = lens.resolve("about_the_docs#design-decisions-captured-here")
matches = lens.locate("design decisions")
outgoing = lens.references(section.ref)
```

See [CLI and Python API](reference.md) for the complete PoC contract.

## 5. Install the agent skill

The Python package includes an official skill synchronized with the installed
Sphinx Lens version. From a project that depends on Sphinx Lens, run:

```bash
uvx library-skills install --skill sphinx-lens --yes
```

[Library Skills](https://library-skills.io/) discovers it inside the package and
can link it into the project's `.agents/skills/` directory.

## 6. Run quality checks

```bash
make qa
make test
```

If `prek` is installed, `make qa` runs the local QA bundle with hooks.

## 7. Build the documentation

```bash
make docs
```

To open generated HTML:

```bash
make docs-open
```
