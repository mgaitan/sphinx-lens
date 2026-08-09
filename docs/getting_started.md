# Getting Started (Tutorial)

This tutorial builds and explores a semantic index for a Sphinx project.

## 1. Create the environment

From the project root:

```bash
uv sync
```

This resolves dependencies and creates the local virtual environment.

## 2. Build an index

Point Sphinx Lens at the directory containing `conf.py`:

```bash
uv run sphinx-lens build docs/
```

The command compiles the sources with the project's own Sphinx configuration and
writes `docs/.sphinx-lens/index.json`.

## 3. Explore the documentation

Search across document titles, section text, and domain objects:

```bash
uv run sphinx-lens locate "semantic index" --index docs/
```

Use a result reference to read only that semantic scope or inspect its metadata:

```bash
uv run sphinx-lens read about_the_docs#information-architecture --index docs/
uv run sphinx-lens inspect about_the_docs#information-architecture --index docs/
uv run sphinx-lens links about_the_docs#information-architecture --index docs/
```

Domain objects have stable references such as `py:class:package.Client` and
`std:term:semantic structure`.

## 4. Use the Python API

```python
from sphinx_lens import Lens

lens = Lens.open("docs/")
section = lens.resolve("about_the_docs#information-architecture")
matches = lens.locate("semantic index")
outgoing = lens.references(section.ref)
```

See [CLI and Python API](reference.md) for the complete PoC contract.

## 5. Run quality checks

```bash
make qa
make test
```

If `prek` is installed, `make qa` runs the local QA bundle with hooks.

## 6. Build the documentation

```bash
make docs
```

To open generated HTML:

```bash
make docs-open
```
