# Django Corpus Evaluation (Explanation)

The first PoC evaluation used the Django documentation because it combines a
large narrative corpus, Python-domain API objects, custom domain objects,
autosection labels, intersphinx, and project-specific Sphinx extensions.

## Reproduce the Build

The recorded run used Django commit `c9eb16a87e60c305fb3651459639f647cce498db`
from August 7, 2026. Its `docs/` tree contains 674 `.txt` source files and is
9.8 MB on disk.

```bash
git clone --depth 1 https://github.com/django/django.git /tmp/django
PYTHONPATH=/tmp/django \
  uv run sphinx-lens build /tmp/django/docs \
  --output /tmp/django-lens/index.json
```

## Results

| Measure | Result |
| --- | ---: |
| Documents indexed | 672 |
| Sections indexed | 6,128 |
| Domain objects indexed | 7,547 |
| Links indexed | 23,095 |
| Internal links | 16,077 |
| External links | 4,634 |
| Unresolved links | 2,384 |
| Resolved links | 89.7% |
| JSON index size | 43.2 MB |
| Build wall time | 71.2 s |
| Peak resident memory | 832 MB |

The run used Python 3.14.4 and Sphinx 9.1.0. Timing and memory are local
observations, not a benchmark across machines. Most peak memory belongs to the
full Sphinx environment and doctrees held during compilation.

A cold CLI query loaded the JSON index and located “database transactions” in
1.31 seconds with 164 MB peak resident memory. Exact title, document, and label
matches ranked first. Inspecting or traversing links for
`py:class:django.db.models.Model` took about 0.6 seconds.

## What the Corpus Exposed

The initial extractor resolved 65.6% of links. Mapping Sphinx role names such as
`meth`, `func`, and `attr` to their domain object types, including roles shared
by multiple types, and normalizing root-relative document paths raised that to
89.7%.

The remaining unresolved references are useful design input. They include
context-dependent domain resolution and intersphinx targets whose semantics are
not present in the local domain inventory. A later index version can record
resolved intersphinx inventory entries and use Sphinx's contextual resolver
without changing the public `Lens` query interface.
