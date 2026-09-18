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
uv run sphinx-lens build
```

Lens finds the nearby `conf.py` and writes `_build/lens/index.sqlite` inside that
Sphinx source directory. The result is an ordinary Sphinx artifact with the same
lifecycle as HTML. A project may cache, publish, or remove it with its
other generated files.

If the project contains generated pages that repeat other content, add their
source-file globs to `lens_no_search` in `conf.py`. Those documents remain
available to `resolve`, `read`, `children`, and `links`, but `locate` skips them.
See {ref}`search-exclusions` for the metadata form and the matching rules.

If discovery finds multiple Sphinx projects, pass the intended source directory.
For a corpus whose `conf.py` is stored separately, pass both paths explicitly:

```bash
uv run sphinx-lens build knowledge/ --conf-dir sphinx/ \
  --doctree-dir /tmp/knowledge-doctrees --output /tmp/knowledge-lens
```

:::{note}
Both forms execute your `conf.py`, exactly like `sphinx-build -b html` does.
Index projects you trust, from a checkout you control.
:::

## Find something

Start with a phrase. `locate` searches titles, canonical names, and scoped body
text, and returns ranked references. Comparisons ignore accents, and Sphinx's
stemmer for the configured language makes inflected terms match when available:

```bash
uv run --group docs sphinx-lens locate "separate artifact"
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
uv run --group docs sphinx-lens locate 'TOKEN$' --regex --kind object
```

In a project with an API, `--domain py` narrows the same query to Python
objects, which is usually what you want for a lookup like
`'QuerySet\.(get|filter)'`. The stemming behaviour follows `language` in
`conf.py`; unsupported languages still get accent folding but no stemming.
When the corpus has directory-based scopes, add
`--under PATH`; repeat it to combine subtrees:

```bash
uv run --group docs sphinx-lens locate "connection timeout" \
  --under guides --under reference
```

## Read only what you need

Hand a reference to `read` and you get that scope's text, composed from the
scope and its descendants. The file it happens to live in does not come with it:

```bash
uv run --group docs sphinx-lens read std:term:PYTHONPATH
```

A glossary term returns its definition. A section returns that section and its
subsections. A class returns the class and its methods. This is the difference
that matters when the consumer is paying by the token.

`inspect` returns the entry as structured JSON, including its physical `location`,
for when you need metadata rather than prose. Pass `--no-text` when the entry
text is not needed.

## Follow the graph

Sphinx resolved every cross-reference in the project while building. `links`
gives you both directions of that graph for any reference:

```bash
uv run --group docs sphinx-lens links std:term:GH_TOKEN
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

lens = Lens.open()
section = lens.resolve("design#why-a-separate-artifact")
matches = lens.locate("separate artifact")
outgoing = lens.references(section.ref)
```

From the repository root or a directory inside the Sphinx sources,
`Lens.open()` discovers the index associated with `conf.py`. Pass an explicit
path only for an index stored outside the conventional project layout.

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
