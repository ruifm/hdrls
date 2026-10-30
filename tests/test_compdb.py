import pytest

from hdrls.compdb import add_header_flags, parse_direct_headers
from hdrls.llm import parse_plan

STDERR = """\
. /usr/include/stdio.h
.. /usr/include/x86_64-linux-gnu/bits/types.h
... /usr/include/x86_64-linux-gnu/bits/wordsize.h
. ../include/foo.h
Multiple include guards may be useful for:
/usr/include/x86_64-linux-gnu/bits/types.h
../include/foo.h
"""


def test_parse_direct_headers_keeps_only_depth_one():
    assert parse_direct_headers(STDERR, "/src/build") == {
        "/usr/include/stdio.h",
        "/src/include/foo.h",
    }


def test_parse_direct_headers_accepts_depth_one_pch():
    assert parse_direct_headers("! /src/pch.h.gch\n!! /src/deep.h\n", "/src") == {"/src/pch.h.gch"}


def test_add_header_flags_splits_quoted_command():
    entry = {"directory": "/src", "file": "a.c", "command": 'cc -DX="a b" -c a.c'}
    argv = add_header_flags(entry)
    assert argv == ["cc", "-DX=a b", "-c", "a.c", "-H", "-fsyntax-only"]


def test_add_header_flags_prefers_arguments():
    entry = {"directory": "/src", "file": "a.c", "arguments": ["cc", "-c", "a.c"], "command": "ignored"}
    assert add_header_flags(entry) == ["cc", "-c", "a.c", "-H", "-fsyntax-only"]


def test_parse_plan_accepts_fenced_json():
    reply = 'Here:\n```json\n{"apt_packages": ["make"], "setup_commands": [], "build_commands": ["make"], "notes": "x"}\n```'
    plan = parse_plan(reply)
    assert plan.apt_packages == ["make"]
    assert plan.build_commands == ["make"]


def test_parse_plan_rejects_empty_build_commands():
    with pytest.raises(ValueError, match="build_commands"):
        parse_plan('{"apt_packages": [], "setup_commands": [], "build_commands": [], "notes": ""}')


def test_parse_plan_rejects_non_string_items():
    with pytest.raises(ValueError, match="apt_packages"):
        parse_plan('{"apt_packages": [1], "setup_commands": [], "build_commands": ["make"]}')
