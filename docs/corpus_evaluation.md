# Real-world corpora

A documentation indexer that only works on the toy project in its own test suite
is worth nothing. This chapter records what happens on documentation nobody
wrote with Sphinx Lens in mind: this project's own MyST docs, Django, and
CPython. Between them they cover MyST and RST, the Python and C domains, custom
domains, autosectionlabel, intersphinx, and project-specific extensions.

Treat these as evidence about extraction quality and retrieval behavior, not as
a benchmark. Timings come from one machine and mean nothing across machines.

## Recorded corpora

| Corpus | Commit | Documents | Sections | Objects | Links | Resolved | Index size |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sphinx Lens | `0a9a8bd` plus this change | 10 | 50 | 6 | 42 | 100% | 58.8 KB |
| Django | `c9eb16a87e60c305fb3651459639f647cce498db` | 672 | 6,128 | 7,547 | 22,471 | 96.5% | 18.8 MB |
| CPython | `998b89020456db591be41e6529b04f4bc8c8181f` | 553 | 5,121 | 19,623 | 57,537 | 96.1% | 35.9 MB |

“Resolved” combines internal and external links. Django produced 17,773
internal, 3,911 external, and 787 unresolved links. CPython produced 48,199
internal, 7,103 external, and 2,235 unresolved links.

The runs used Python 3.14.4, Sphinx 9.1.0, and cached Sphinx doctrees when
available. The observed build times and peak resident memory were 45.4 seconds
and 285 MB for Django, and 128.9 seconds and 528 MB for CPython.

## Sphinx Lens: MyST and glossary precision

The project builds its own index without listing `sphinx_lens` in `conf.py`:

```bash
make lens
```

All 42 links were classified as internal or external. This specifically checks
that MyST document links pass through Sphinx's resolver instead of remaining
raw `pending_xref` nodes. Reading the glossary object also returns the precise
definition rather than the complete configuration page:

```console
$ sphinx-lens read std:term:PYTHONPATH -i docs/_build/lens
PYTHONPATH

Python import search path.
In this project docs, it is used for module execution from source (for example PYTHONPATH=src uv run -m ...).
```

## Django: narrative and ORM API

Build from Django's own documentation environment so its package imports and
extensions are available:

```bash
PYTHONPATH=/tmp/django sphinx-lens build /tmp/django/docs \
  --output /tmp/django-lens
```

A concept query puts the exact label and document first, followed by the most
specific subsection and API objects:

```console
$ sphinx-lens locate "database transactions" -i /tmp/django-lens --limit 5
1.00  std:label:topics/db/transactions:database transactions
1.00  topics/db/transactions
0.90  std:label:topics/db/transactions:managing database transactions
0.70  py:exception:django.db.transaction.TransactionManagementError
0.70  py:function:django.db.transaction.atomic
```

Regex plus domain filtering locates exact Python objects without relying on
body ranking:

```console
$ sphinx-lens locate '^django\.db\.models\.(Model|query\.QuerySet)$' \
    --regex --kind object --domain py --json -i /tmp/django-lens
py:class:django.db.models.Model              ref/models/instances#django.db.models.Model
py:class:django.db.models.query.QuerySet     ref/models/querysets#django.db.models.query.QuerySet
```

The graph reports 17 incoming and 13 outgoing links for `Model`, and 41 incoming
and 3 outgoing links for `QuerySet`. A cold CLI process loaded the JSON and ran
the first query in 1.08 seconds with 97 MB peak resident memory.

## CPython: mixed Python and C domains

```bash
PYTHONPATH=/tmp/cpython sphinx-lens build /tmp/cpython/Doc \
  --output /tmp/cpython-lens
```

The natural-language query returns the canonical glossary term first and then
relevant narrative scopes:

```console
$ sphinx-lens locate "global interpreter lock" -i /tmp/cpython-lens --limit 5
1.00  std:term:global interpreter lock
0.90  c-api/threads
0.90  faq/library#can-t-we-get-rid-of-the-global-interpreter-lock
0.90  howto/free-threading-python#the-global-interpreter-lock-in-free-threaded-python
0.90  std:label:threads
```

Two structural queries demonstrate that the same interface spans domains:

```console
$ sphinx-lens locate '^asyncio\.(Task|TaskGroup)$' --regex --kind object --domain py --json -i /tmp/cpython-lens
py:class:asyncio.Task        library/asyncio-task#asyncio.Task
py:class:asyncio.TaskGroup   library/asyncio-task#asyncio.TaskGroup

$ sphinx-lens locate '^PyObject_(Call|GetAttrString)$' --regex --kind object --domain c --json -i /tmp/cpython-lens
c:function:PyObject_Call            c-api/call#c.PyObject_Call
c:function:PyObject_GetAttrString   c-api/object#c.PyObject_GetAttrString
```

`std:term:global interpreter lock` has 25 incoming links. `asyncio.Task` has 45
incoming and 46 outgoing links. The GIL query took 1.63 seconds and 151 MB peak
resident memory in a new CLI process.

## Findings and limits

- Sphinx-resolved doctrees handle MyST, contextual domain lookup, and local
  cross-references more accurately than a Lens-specific resolver.
- Storing only each entry's own text reduced the large-corpus artifacts while
  keeping `read` able to compose complete scopes.
- JSON remains expensive to parse for repeated queries. SQLite with FTS5 is a
  likely later backend once the index contract stabilizes.
- Normalized `astext()` output does not distinguish prose, code, tables, and
  admonitions. Source ranges and a source-preserving read mode need separate
  design work.
- Remaining unresolved links include intersphinx and extension-specific targets
  that do not resolve into a local physical location.
