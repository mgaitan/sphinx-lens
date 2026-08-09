# Getting started

This walkthrough builds an index for a Sphinx project and then answers a few
questions with it. It uses this repository's own documentation as the corpus, so
you can follow along by cloning it, but every step works the same against any
Sphinx project.

## Set up the environment

Sphinx Lens runs *inside* your documentation build. It has to import the same
MyST, autodoc, theme, and extension packages your `conf.py` imports, which means
it belongs in the same environment as your docs dependencies rather than in an
isolated one.

From the project root:

```bash
uv sync --group docs
```

That resolves dependencies and creates the local virtual environment. In your
own project, add `sphinx-lens` to whichever group already holds `sphinx`.

## Build the index

Sphinx Lens registers a builder named `lens` through Sphinx's entry points, so
it is available as soon as the package is installed. You do not have to list it
in `extensions`:

```bash
uv run --group docs sphinx-build -b lens docs/ docs/_build/lens/
```

The result is `docs/_build/lens/index.json`: an ordinary Sphinx artifact, in the
same place as your HTML, with the same lifecycle. `make clean` removes it along
with everything else, and CI can cache or publish it the way it already caches
or publishes builds. This repository exposes the command as `make lens`.

If you prefer a single command that does not require you to spell out the paths,
`uv run sphinx-lens build docs/` wraps the same builder and writes to the same
default location.

:::{note}
Both forms execute your `conf.py`, exactly like `sphinx-build -b html` does.
Index projects you trust, from a checkout you control.
:::

## Find something

Start with a phrase. `locate` searches titles, canonical names, and scoped body
text, and returns ranked references:

```bash
uv run --group docs sphinx-lens locate "separate artifact" --index docs/_build/lens/
```

Each result line begins with the reference you use everywhere else. There are
three shapes, and they are stable across builds:

| Shape | Example | What it is |
| --- | --- | --- |
| Document | `getting_started` | A source file |
| Section | `design#why-a-separate-artifact` | A heading and its content |
| Domain object | `std:term:PYTHONPATH`, `py:class:example.Client` | Anything Sphinx's domains know about |

When you already know the shape of what you want, say so and skip the ranking
entirely. This finds every documented object whose name ends in `TOKEN`:

```bash
uv run --group docs sphinx-lens locate 'TOKEN$' --regex --kind object \
  --index docs/_build/lens/
```

In a project with an API, `--domain py` narrows the same query to Python
objects, which is usually what you want for a lookup like
`'QuerySet\.(get|filter)'`.

## Read only what you need

Hand a reference to `read` and you get that scope's text, composed from the
scope and its descendants. The file it happens to live in does not come with it:

```bash
uv run --group docs sphinx-lens read std:term:PYTHONPATH --index docs/_build/lens/
```

A glossary term returns its definition. A section returns that section and its
subsections. A class returns the class and its methods. This is the difference
that matters when the consumer is paying by the token.

`inspect` returns the same entry as structured JSON (kind, title, document,
anchor, parent, domain) for when you need the metadata rather than the prose.

## Follow the graph

Sphinx resolved every cross-reference in the project while building. `links`
gives you both directions of that graph for any reference:

```bash
uv run --group docs sphinx-lens links std:term:GH_TOKEN --index docs/_build/lens/
```

That returns the two chapters that mention the term, resolved down to the exact
section each mention came from.

Outgoing links tell you what a scope depends on. Incoming links tell you which
parts of the documentation consider it relevant, which is often a better ranking
signal than any text search: a concept cited from twenty places is the one the
project actually treats as central, whether or not it uses the words you
searched for.

## Use it from Python

Everything the CLI does is a thin layer over the `Lens` object:

```python
from sphinx_lens import Lens

lens = Lens.open("docs/_build/lens/")
section = lens.resolve("design#why-a-separate-artifact")
matches = lens.locate("separate artifact")
outgoing = lens.references(section.ref)
```

`Lens.open()` also warns when the sources it was built from have changed on
disk, so a stale index says so rather than answering with last week's
documentation.

[CLI and Python API](reference.md) documents the full surface.

## Give it to an agent

The package ships an agent skill that teaches a coding agent this workflow:
locate, then read the narrowest useful scope, then follow links only if needed.
From a project that depends on Sphinx Lens:

```bash
uvx library-skills install --skill sphinx-lens --yes
```

[Library Skills](https://library-skills.io/) finds the skill inside the
installed package and links it into the project's `.agents/skills/` directory,
so it stays in sync with the version you have installed.

## Next steps

- [How it works](design.md) covers the model behind the index and why it is a
  separate artifact rather than a reuse of `objects.inv` or `searchindex.js`.
- [Real-world corpora](corpus_evaluation.md) reports what happens on Django and
  CPython, including the parts that do not work yet.
- [Development workflow](development_workflow.md) is for contributors.
