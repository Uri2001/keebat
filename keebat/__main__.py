"""Entry point for `python -m keebat` and the `keebat` console script."""

import sys

from .app import run


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
