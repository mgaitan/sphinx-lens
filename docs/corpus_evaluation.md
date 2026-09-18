# Real-world corpora

A documentation indexer that only works on the toy project in its own test suite
is worth nothing. This chapter records what happens on documentation nobody
wrote with Sphinx Lens in mind: this project's own MyST docs, Django, CPython,
and the public MyST-Parser documentation. Together they cover MyST and RST,
narrative articles, the Python and C domains, custom domains, autosectionlabel,
intersphinx, and project-specific extensions.

Treat these as evidence about extraction quality and retrieval behavior. They
are no kind of benchmark: the timings come from one machine and mean nothing
across machines.

## Recorded corpora

| Corpus | Commit | Documents | Sections | Objects | Links | Resolved | Index size |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sphinx Lens | `a7053be` plus this change | 10 | 51 | 6 | 45 | 100% | 66.5 KB |
| Django | `c9eb16a87e60c305fb3651459639f647cce498db` | 672 | 6,128 | 7,547 | 22,367 | 96.9% | 18.2 MB |
| CPython | `998b89020456db591be41e6529b04f4bc8c8181f` | 553 | 5,121 | 19,623 | 56,303 | 98.2% | 34.6 MB |
| MyST Parser | [`723cffc`](https://github.com/executablebooks/MyST-Parser/tree/723cffcf84213f0cb58695b27eec9ad72052b53a) | 28 | 239 | 73 | 541 | 98.5% | 410 KB |

“Resolved” combines internal and external links. Django produced 17,773
internal, 3,911 external, and 683 unresolved links. CPython produced 48,198
internal, 7,103 external, and 1,002 unresolved links. The MyST Parser run
produced 184 internal, 349 external, and 8 unresolved links after anchored
targets were checked. Its 98.5% figure counts internal and external links as
resolved; `unresolved` means that Lens could not verify a local target or could
not resolve the reference. This classification does not test whether an
external URL is reachable.

The Django and CPython index sizes predate the extraction fix that stores the
prose a document was titled from, so both are smaller than a current run would
produce. Entry and link counts are unaffected. Recomputing them is tracked in
[issue #17](https://github.com/mgaitan/sphinx-lens/issues/17).

The runs used Python 3.14.4, Sphinx 9.1.0, and cached Sphinx doctrees when
available. The observed build times and peak resident memory were 39.9 seconds
and 287 MB for Django, and 104.6 seconds and 497 MB for CPython.

## SQLite prototype: Fierro knowledge base

Issue [#43](https://github.com/mgaitan/sphinx-lens/issues/43) replaced the JSON
artifact with SQLite and FTS5. The comparison used the same Spanish index from
`~/lambda/kb`: 1,000 documents, 2,853 entries, 2,432 links, and 185 documents
excluded from search. The JSON baseline ran from an unmodified `main` worktree;
the SQLite branch rebuilt the same corpus with cached doctrees.

| Measurement | JSON on `main` | SQLite prototype |
| --- | ---: | ---: |
| Artifact size | 6,465,972 bytes | 20,185,088 bytes |
| gzip size | 888,055 bytes | 8,695,519 bytes |
| Full build with fresh doctrees | 34.35 s | 25.81 s |
| Build peak resident memory | 361,356 KB | 344,060 KB |
| Rebuild with no source changes | 8.51 s | 7.28 s |
| Storage write from the same extracted model | 0.69 s | 1.00 s |
| `Lens.open()` | 96 ms | 26 ms |
| Five representative queries | 10.19-10.41 s each | 18-106 ms each |
| New CLI process, `cargar productos con IVA` | 10.92 s | 0.40 s |
| CLI peak resident memory | 61,716 KB | 51,648 KB |

The five queries covered product VAT, copying user groups, Mercado Libre stock,
Paraguayan electronic invoices, and importing receipts from a bank statement.
Their top-five references had the same order under both backends. The SQLite
process did not materialize the complete `entries` table while running these
normal text searches.

The database is larger because it contains the complete document metadata and
source hashes, the extracted entry text, B-tree indexes for navigation, and two
contentless FTS indexes. The trigram index preserves the previous substring
search behavior, but makes the compressed SQLite artifact almost ten times the
size of compressed JSON. This prototype favors query behavior and
inspectability over compressed artifact size. The build wrote to a temporary
database and replaced the final file after closing it; the artifact directory
contained no journal or WAL sidecars. It does not yet update SQLite
incrementally: the Lens builder writes every cached doctree and rebuilds the
database even when Sphinx finds no changed sources.

PyStemmer is a required dependency. Sphinx selects its C implementation through
`snowballstemmer`; on this corpus, rebuilding with cached doctrees dropped from
14.08 seconds to 7.28 seconds while producing the same Spanish stems.

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
- SQLite opens metadata without loading all entries and uses FTS5 to select
  normal-search candidates. Regex queries still scan the filtered entry rows.
- Normalized `astext()` output does not distinguish prose, code, tables, and
  admonitions.
- Remaining unresolved links include intersphinx and extension-specific targets
  that do not resolve into a local physical location.
