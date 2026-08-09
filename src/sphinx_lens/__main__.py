"""Run Sphinx Lens as a module."""

import sys

from sphinx_lens import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
