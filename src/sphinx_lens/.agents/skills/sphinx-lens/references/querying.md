# Sphinx Lens Query Reference

## Build

Run the builder from the project's documentation environment; Sphinx discovers
it from the installed package without a `conf.py` change:

```bash
sphinx-build -b lens docs docs/_build/lens
```

Use `sphinx-lens build docs` as the equivalent convenience command. Both forms
execute `conf.py` and require all configured documentation dependencies.

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
  -i docs/_build/lens \
  | jq -r '.[] | [.entry.ref, .entry.location, .score] | @tsv'
```

Query the full index model when ranking is unnecessary:

```bash
jq -r '.entries[] | select(.kind == "object" and .object_type == "class") | .ref' \
  docs/_build/lens/index.json
jq -r '.links[] | select(.kind == "unresolved") | .target' \
  docs/_build/lens/index.json | sort | uniq -c | sort -nr
rg -n -i 'transaction|atomic' docs/_build/lens/index.json
```

Prefer `jq` for fields and relationships. Prefer `rg` for a quick literal or
regex scan across the artifact.

## Python API

```python
from sphinx_lens import Lens

lens = Lens.open("docs/_build/lens")
matches = lens.locate(r"QuerySet\.(get|filter)", regex=True, kinds={"object"}, domain="py")
entry = lens.resolve("py:class", "django.db.models.Model")
text = lens.read(entry.ref)
links = lens.linked(entry.ref)
```
