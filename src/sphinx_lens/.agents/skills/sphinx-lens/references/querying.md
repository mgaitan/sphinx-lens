# Sphinx Lens Query Reference

## Build

From the repository or Sphinx source tree, let Lens discover the applicable
`conf.py`:

```bash
sphinx-lens build
```

This writes `_build/lens/index.sqlite` inside the discovered source directory. If
multiple Sphinx projects are present, select one explicitly with
`sphinx-lens build path/to/sphinx-source`. The equivalent native Sphinx command
is:

```bash
sphinx-build -b lens path/to/sphinx-source path/to/sphinx-source/_build/lens
```

Both forms execute that `conf.py` and require all configured documentation
dependencies. Use a project-specific wrapper only when the repository documents
one.

## Locate

```bash
sphinx-lens locate "database transactions"
sphinx-lens locate '^(django\.)?db\..*Model$' --regex --kind object --domain py
sphinx-lens locate 'timeout|deadline' --regex --kind section --json
```

The first form ranks text terms. Regex uses Python `re` with case-insensitive
matching across the canonical reference, title, object name, and normalized
body text.

## Inspect and Navigate

```bash
sphinx-lens inspect py:class:django.db.models.Model
sphinx-lens read topics/db/transactions
sphinx-lens links topics/db/transactions
```

Use `inspect` for metadata, `read` for normalized scoped text, and `links` for
incoming plus outgoing references. These commands discover the index associated
with a nearby Sphinx `conf.py`; pass `-i PATH` only for a nonstandard artifact.

## Compose with jq and rg

Project structured search results:

```bash
sphinx-lens locate 'QuerySet\..*' --regex --kind object --domain py --json \
  -i path/to/index \
  | jq -r '.[] | [.entry.ref, .entry.location, .score] | @tsv'
```

Query the full index model when ranking is unnecessary:

```bash
sphinx-lens entries --json -i path/to/index \
  | jq -r '.[] | select(.kind == "object" and .object_type == "class") | .ref'
sphinx-lens links --all --json -i path/to/index \
  | jq -r '.[] | select(.kind == "unresolved") | .target' \
  | sort | uniq -c | sort -nr
sphinx-lens dump --json -i path/to/index | rg -n -i 'transaction|atomic'
```

Prefer `jq` for fields and relationships. Prefer `rg` over `dump --json` for a
quick literal or regex scan across the exported model.

## Python API

```python
from sphinx_lens import Lens

lens = Lens.open()
matches = lens.locate(r"QuerySet\.(get|filter)", regex=True, kinds={"object"}, domain="py")
entry = lens.resolve("py:class", "django.db.models.Model")
text = lens.read(entry.ref)
links = lens.linked(entry.ref)
```
