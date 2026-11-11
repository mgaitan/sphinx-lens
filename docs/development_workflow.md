# Development workflow

The most common maintenance tasks, in roughly the order you hit them.

## Build the documentation

```bash
make docs        # HTML, with warnings as errors
make docs-open   # build and open in a browser
make lens        # this project's own Sphinx Lens index
```

`make lens` is worth running on any documentation change: this repository is one
of the corpora in [Real-world corpora](corpus_evaluation.md), so its own index
is the fastest way to notice an extraction regression.

## Use the pinned Python

The generated `.python-version` records the exact Python interpreter that ran
Copier. `uv` uses this file automatically, and template updates preserve it.

## Run local QA before pushing

```bash
make qa
make test
```

If `prek` is not installed, install it once with:

```bash
uv tool install prek
```

## Update dependencies safely

This template uses `uv` groups and cooldown windows.
After dependency changes:

```bash
uv sync
make qa
make test
```

## Publish a release

```bash
make bump
make release
```

The release workflow builds and publishes package artifacts to PyPI. After a
successful publication, the `release-docs` job dispatches `cd.yml` on `main` to
publish the canonical docs. The dispatch job has `actions: write` permission;
the package-publishing job does not.

Release events run on tags, but the `github-pages` environment permits only
`main`. The release run therefore skips direct documentation deployment. The
dispatched run deploys docs from `main`, not from the release tag, and never
publishes a package. If that deployment fails, rerun it with the
{ref}`manual dispatch command below <manual-docs-deployment>`
without repeating the PyPI upload.

Unlike the Copier template's own release workflow, Sphinx Lens does not update
`mgaitan/yet-another-demo`. That repository tracks releases of
`mgaitan/python-package-copier-template`, not Sphinx Lens packages.

### Verify release attestations

Each wheel and source distribution has a PEP 740 publish attestation signed
through Sigstore and uploaded to PyPI with the package.

Verify a published artifact by passing its PyPI file URL:

```bash
uvx pypi-attestations verify pypi \
  --repository https://github.com/mgaitan/sphinx-lens \
  https://files.pythonhosted.org/path/to/distribution.whl
```

(manual-docs-deployment)=
## Preview documentation in pull requests

When docs files change in a PR, CI deploys a preview to:

```text
https://mgaitan.github.io/sphinx-lens/_preview/pr-<PR_NUMBER>/
```

If needed, dispatch docs publishing manually:

```bash
gh workflow run cd.yml --ref main
```

`gh` authentication can use {term}`GH_TOKEN`.
