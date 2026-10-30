"""Add header-tracing flags to compile commands and collect direct headers."""

import json
import posixpath
import re
import shlex
from pathlib import Path

from . import log

HEADER_FLAGS = ["-H", "-fsyntax-only"]
REALPATH_CHUNK = 500

# `-H` prints one mark per include depth. A single `.` is a depth-1 include;
# GCC prints a single `!` for a valid precompiled header at depth 1. Deeper
# lines (`.. `, `... `) and the "Multiple include guards" block do not match.
DIRECT_RE = re.compile(r"^[.!] (.+)$")


class HeaderPassFailed(RuntimeError):
    pass


def add_header_flags(entry: dict) -> list[str]:
    argv = list(entry["arguments"]) if "arguments" in entry else shlex.split(entry["command"])
    # -fsyntax-only stops object writes, so build outputs are not clobbered.
    return argv + HEADER_FLAGS


def modified_entries(entries: list[dict]) -> list[dict]:
    return [
        {"directory": e["directory"], "file": e["file"], "arguments": add_header_flags(e)}
        for e in entries
    ]


def write_modified_db(entries: list[dict], path: Path) -> list[dict]:
    modified = modified_entries(entries)
    path.write_text(json.dumps(modified, indent=2) + "\n")
    return modified


def parse_direct_headers(stderr: str, directory: str) -> set[str]:
    headers = set()
    for line in stderr.splitlines():
        m = DIRECT_RE.match(line)
        if m:
            p = m.group(1).rstrip()
            headers.add(posixpath.normpath(posixpath.join(directory, p)))
    return headers


def collect_direct_headers(session, entries: list[dict]) -> list[str]:
    headers: set[str] = set()
    failed = 0
    for entry in entries:
        proc = session.exec(entry["arguments"], cwd=entry["directory"])
        if proc.returncode != 0:
            failed += 1
            log(f"header pass failed for {entry['file']} (exit {proc.returncode})")
        headers |= parse_direct_headers(proc.stderr, entry["directory"])
    if entries and failed == len(entries):
        raise HeaderPassFailed("every header pass command failed")

    # Canonicalize inside the container: paths such as
    # /usr/lib/gcc/.../../../../include only resolve there.
    ordered = sorted(headers)
    resolved: set[str] = set()
    for i in range(0, len(ordered), REALPATH_CHUNK):
        chunk = ordered[i : i + REALPATH_CHUNK]
        proc = session.exec(["realpath", "-e", "--", *chunk], cwd="/")
        resolved.update(line for line in proc.stdout.splitlines() if line)
        for line in proc.stderr.splitlines():
            log(f"dropping unresolved header: {line}")
    return sorted(resolved)
