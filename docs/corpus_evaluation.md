# Real-world corpora

A documentation indexer that only works on the toy project in its own test suite
is worth nothing. This chapter records what happens on documentation nobody
wrote with Sphinx Lens in mind: this project's own MyST docs, Django, CPython, and the Fierro knowledge base.
Between them they cover MyST and RST, narrative articles, the Python and C
domains, custom domains, autosectionlabel, intersphinx, and project-specific
extensions.

Treat these as evidence about extraction quality and retrieval behavior. They
are no kind of benchmark: the timings come from one machine and mean nothing
across machines.

## Recorded corpora

| Corpus | Commit | Documents | Sections | Objects | Links | Resolved | Index size |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sphinx Lens | `a7053be` plus this change | 10 | 51 | 6 | 45 | 100% | 66.5 KB |
| Django | `c9eb16a87e60c305fb3651459639f647cce498db` | 672 | 6,128 | 7,547 | 22,367 | 96.9% | 18.2 MB |
| CPython | `998b89020456db591be41e6529b04f4bc8c8181f` | 553 | 5,121 | 19,623 | 56,303 | 98.2% | 34.6 MB |
| Fierro knowledge base | `fe311c1` | 977 | 1,771 | 0 | 2,567 | 97.3% | 5.5 MB |

“Resolved” combines internal and external links. Django produced 17,773
internal, 3,911 external, and 683 unresolved links. CPython produced 48,198
internal, 7,103 external, and 1,002 unresolved links. The Fierro run produced
1,683 internal, 815 external, and 69 unresolved links after anchored targets
were checked. Its 97.3% figure counts internal and external links as resolved;
`unresolved` means that Lens could not verify a local target or could not resolve
the reference. This classification does not test whether an external URL is
reachable.

The Django and CPython index sizes predate the extraction fix that stores the
prose a document was titled from, so both are smaller than a current run would
produce. Entry and link counts are unaffected. Recomputing them is tracked in
[issue #17](https://github.com/mgaitan/sphinx-lens/issues/17).

The runs used Python 3.14.4, Sphinx 9.1.0, and cached Sphinx doctrees when
available. The observed build times and peak resident memory were 39.9 seconds
and 287 MB for Django, and 104.6 seconds and 497 MB for CPython.

## Sphinx Lens: MyST and glossary precision

The project builds its own index without listing `sphinx_lens` in `conf.py`:

```bash
make lens
```

The current index contains 49 links: 28 internal and 21 external, with no
unresolved links. The historical row above records 45 links from an earlier
snapshot. This specifically checks that MyST document links pass through Sphinx's
resolver instead of remaining raw `pending_xref` nodes. Reading a document also
returns its opening prose
rather than starting at the first subheading, which is what a MyST corpus makes
easy to get wrong:

```console
$ sphinx-lens read design -i docs/_build/lens | head -3
How it works

Sphinx Lens runs as a Sphinx build. Most of the rest follows from that one
```

Reading the glossary object returns the precise definition rather than the
complete configuration page:

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
incoming and 45 outgoing links. The GIL query took 1.63 seconds and 151 MB peak
resident memory in a new CLI process.

## Findings and limits

- Sphinx-resolved doctrees handle MyST, contextual domain lookup, and local
  cross-references more accurately than a Lens-specific resolver. Taking the
  unresolved set from Sphinx's own `missing-reference` event, instead of
  reconstructing it by matching labels, removed a further 104 false negatives on
  Django and 1,233 on CPython.
- Storing only each entry's own text reduced the large-corpus artifacts while
  keeping `read` able to compose complete scopes.
- JSON is parsed in full on every open, so a cold process pays roughly a second
  on these corpora before answering anything.
- Normalized `astext()` output does not distinguish prose, code, tables, and
  admonitions.
- Remaining unresolved links include intersphinx and extension-specific targets
  that do not resolve into a local physical location.
