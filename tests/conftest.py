"""Configuration for the pytest test suite."""

from pathlib import Path

import pytest


@pytest.fixture
def sphinx_project(tmp_path: Path) -> Path:
    """Create a small Sphinx corpus with domains and cross-references."""
    project = tmp_path / "docs"
    project.mkdir()
    (project / "conf.py").write_text('project = "Lens Fixture"\nextensions = []\n', encoding="utf-8")
    (project / "index.rst").write_text(
        """Lens Fixture
============

See :doc:`guide`, :class:`demo.Client`, and :class:`Missing`.

.. toctree::

   guide
   api
""",
        encoding="utf-8",
    )
    (project / "guide.rst").write_text(
        """Guide
=====

Connection timeout
------------------

Configure the connection timeout before creating a :class:`demo.Client`.

See :ref:`retry-policy`, `Python <https://python.org>`_, and `HTML guide <guide.html>`_.

.. _retry-policy:

Retry policy
------------

Retry twice.

Glossary
--------

See :term:`connection budget`.

.. glossary::

   connection budget
      The total time allowed for connection attempts.
""",
        encoding="utf-8",
    )
    (project / "api.rst").write_text(
        """API
===

.. py:module:: demo

.. py:class:: Client(timeout=30)

   A network client.

   .. py:method:: connect()

      Connect to the service. See :doc:`guide`.
""",
        encoding="utf-8",
    )
    return project
