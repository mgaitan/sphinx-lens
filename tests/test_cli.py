"""Tests for the CLI."""

from __future__ import annotations

import json
import runpy
import sys
from importlib import metadata
from typing import TYPE_CHECKING

import pytest

from sphinx_lens import get_version, main

if TYPE_CHECKING:
    from pathlib import Path


def test_main():
    """Basic CLI test."""
    assert main([]) == 0


def test_show_help(capsys: pytest.CaptureFixture):
    """Show help.

    Parameters:
        capsys: Pytest fixture to capture output.
    """
    with pytest.raises(SystemExit):
        main(["-h"])
    captured = capsys.readouterr()
    assert "sphinx-lens" in captured.out


def test_show_version(mocker, capsys: pytest.CaptureFixture):
    """Show version.

    Parameters:
        mocker: pytest-mock fixture to patch get_version.
        capsys: Pytest fixture to capture output.
    """
    mocker.patch("sphinx_lens.get_version", return_value="0.1.0")
    with pytest.raises(SystemExit):
        main(["-V"])
    captured = capsys.readouterr()
    assert "0.1.0" in captured.out


def test_main_module(mocker):
    """Test running the CLI via __main__ (python -m ...)."""
    module_name = "sphinx_lens.__main__"
    # Simulate: python -m sphinx-lens --version
    mocker.patch.object(sys, "argv", ["sphinx-lens", "-V"])
    with pytest.raises(SystemExit):
        runpy.run_module(module_name, run_name="__main__", alter_sys=False)


def test_get_version_package_not_found(mocker):
    """Test get_version returns 'unknown' if package is not found."""
    mocker.patch(
        "importlib.metadata.version",
        side_effect=metadata.PackageNotFoundError("not found"),
    )
    assert get_version() == "unknown"


def test_build_and_query_commands(sphinx_project: Path, tmp_path: Path, capsys: pytest.CaptureFixture):
    """The CLI builds and queries the same portable index."""
    output = tmp_path / "lens"
    doctree_dir = tmp_path / "doctrees"
    assert (
        main(
            [
                "build",
                str(sphinx_project),
                "--output",
                str(output),
                "--conf-dir",
                str(sphinx_project),
                "--doctree-dir",
                str(doctree_dir),
            ]
        )
        == 0
    )
    assert doctree_dir.is_dir()
    build_output = capsys.readouterr().out
    assert "Indexed 3 documents" in build_output
    assert "(0 warnings)" in build_output

    assert main(["locate", "connection timeout", "--index", str(output), "--limit", "1", "--under", "guide"]) == 0
    assert "guide#connection-timeout" in capsys.readouterr().out

    assert (
        main(
            [
                "locate",
                "timeout(s)?",
                "--regex",
                "--kind",
                "section",
                "--json",
                "--index",
                str(output),
            ]
        )
        == 0
    )
    results = json.loads(capsys.readouterr().out)
    assert results[0]["entry"]["ref"] == "guide#connection-timeout"
    assert results[0]["entry"]["location"] == "guide#connection-timeout"

    assert main(["inspect", "py:class:demo.Client", "--index", str(output)]) == 0
    inspect_output = json.loads(capsys.readouterr().out)
    assert inspect_output["kind"] == "object"
    assert inspect_output["location"] == "api#demo.Client"

    assert main(["inspect", "py:class:demo.Client", "--no-text", "--index", str(output)]) == 0
    assert "text" not in json.loads(capsys.readouterr().out)

    assert main(["read", "guide#retry-policy", "--index", str(output)]) == 0
    assert "Retry twice" in capsys.readouterr().out

    assert main(["links", "guide#connection-timeout", "--index", str(output)]) == 0
    assert '"outgoing"' in capsys.readouterr().out


def test_query_error(capsys: pytest.CaptureFixture):
    """CLI query failures return a non-zero status."""
    assert main(["read", "missing", "--index", "/does/not/exist"]) == 1
    assert "Lens index not found" in capsys.readouterr().err
