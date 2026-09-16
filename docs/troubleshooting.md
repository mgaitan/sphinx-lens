# Troubleshooting

This chapter covers the failures and warnings that are easiest to encounter when
indexing a Sphinx project that was not designed for Lens. Start by keeping the
source tree unchanged and make the build configuration explicit; most symptoms
then have a direct explanation.

## Decide which warnings matter

A Lens build can succeed while Sphinx reports warnings. Read the warning category
before deciding whether to suppress it:

- `toc.not_included` means that a document is not reachable from a toctree. Lens
  still indexes it because it reads `env.found_docs`. Suppress this category when
  the corpus intentionally has incomplete or no toctrees:

  ```python
  suppress_warnings = ["toc.not_included"]
  ```

- `myst.header` means that heading levels are not consecutive. It usually points
  to source structure that affects section boundaries and should be fixed or
  tracked as content debt.

- `myst.xref_missing` means that MyST could not resolve a cross-reference. Lens
  records such references as `unresolved`; do not treat a successful build as
  proof that every link works.

Use `-W` with `sphinx-build` or `fail_on_warning=True` with the Python API when
warnings must fail the build. The native `sphinx-build` command displays the
warning details and categories. The successful `sphinx-lens build` wrapper
captures those details while building and reports only its aggregate result; it
does not persist Sphinx warning messages in the Lens index. Use the native
command with the same source and configuration when you need to inspect a
category before deciding whether to suppress it.

## `conf.py` lives outside the source tree

Pass the configuration directory separately instead of copying `conf.py` into an
exported corpus. The directory must contain the project's `conf.py`, and it must
be able to import the extensions used by that project:

```bash
sphinx-lens build knowledge/ \
  --conf-dir sphinx/ \
  --doctree-dir /tmp/knowledge-doctrees \
  --output /tmp/knowledge-lens
```

`--doctree-dir` is separate for the same reason: Sphinx's cache should not write
into a generated or read-only source tree. The equivalent Python call is:

```python
from sphinx_lens import build

lens = build(
    "knowledge/",
    "/tmp/knowledge-lens",
    conf_dir="sphinx/",
    doctree_dir="/tmp/knowledge-doctrees",
)
```

When Sphinx cannot import a configured extension, fix the environment rather than
adding a second parser. Lens must run in the same environment as the documentation
build.

## The index says that staleness cannot be checked

An index built outside the source tree stores `"source": null` because no relative
source path would survive moving the artifact. `Lens.open()` emits a
`StaleIndexWarning` in that case. The warning is intentional: the index remains
readable, but Lens cannot compare its recorded document hashes with files on disk.

To enable the check, put the artifact below the source tree, for example:

```bash
sphinx-lens build docs/ --output docs/_build/lens
```

If the artifact must be published elsewhere, keep the warning and treat the
artifact as a snapshot. Rebuilding it is the way to refresh it after source
changes.

## `read` returns only a title

Older indexes were able to lose the prose between a document title and its first
subheading. Current extraction assigns that text to the document entry when the
top-level section is collapsed into the document reference. Rebuild an index that
was created before this fix:

```bash
sphinx-lens build docs/ --output docs/_build/lens
```

If the rebuilt result is still empty, inspect the source. A genuinely empty
article or a generated stub may contain a title and no body text. Use
`locate --kind section` to search for a narrower scope, and use `inspect --no-text`
when checking structure without printing the full text.

## `Lens.open()` rejects the index

Lens indexes have a versioned JSON contract. An error such as
`Unsupported Lens index version: 3; rebuild the index with the current version`
means that the artifact was created by an older Lens release. It is not safe to
reinterpret the old payload as the current schema, so rebuild it with the same
Sphinx project and dependencies:

```bash
sphinx-build -b lens -c sphinx/ knowledge/ /tmp/knowledge-lens
```

If the error instead says `Lens index not found`, pass either the directory that
contains `index.json` or the path to the file itself. `--index` accepts both forms
for query commands.
