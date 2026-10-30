"""List the headers that an upstream C/C++ project includes directly."""

import sys


def log(msg: str) -> None:
    print(f"hdrls: {msg}", file=sys.stderr, flush=True)
