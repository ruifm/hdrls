"""Command-line entry point."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from . import builder, compdb, container, llm, log, repo

DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"


def default_workdir(url: str) -> Path:
    name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or "repo"
    digest = hashlib.sha256(url.encode()).hexdigest()[:8]
    return Path.home() / ".cache" / "hdrls" / f"{name}-{digest}"


def run(url, workdir, api_key, model, max_attempts, build_timeout, chat_fn=llm.chat) -> list[str]:
    workdir = Path(workdir).resolve()
    src = workdir / "src"
    out = workdir / "out"
    repo.clone(url, src)
    tag, _plan = builder.build_until_success(
        url, src, workdir, api_key, model, max_attempts, build_timeout, chat_fn=chat_fn
    )
    entries = json.loads((out / container.COMPDB_NAME).read_text())
    modified = compdb.write_modified_db(entries, out / "compile_commands.headers.json")
    log(f"running header pass on {len(modified)} compile commands")
    with container.Session(tag, src, out) as session:
        return compdb.collect_direct_headers(session, modified)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="hdrls", description="List the headers that a C/C++ project includes directly."
    )
    p.add_argument("url", help="upstream git repository URL (or local path)")
    p.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model id")
    p.add_argument("--max-attempts", type=int, default=5, help="LLM plans to try (default 5)")
    p.add_argument("--workdir", type=Path, help="work directory (default ~/.cache/hdrls/<slug>)")
    p.add_argument("--build-timeout", type=int, default=3600, help="seconds per build attempt")
    p.add_argument("--output", type=Path, help="also write the list to this file")
    args = p.parse_args(argv)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("error: OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 2
    if args.max_attempts < 1:
        print("error: --max-attempts must be at least 1", file=sys.stderr)
        return 2

    workdir = args.workdir or default_workdir(args.url)
    try:
        headers = run(args.url, workdir, api_key, args.model, args.max_attempts, args.build_timeout)
    except (builder.BuildFailed, compdb.HeaderPassFailed) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    text = "".join(f"{h}\n" for h in headers)
    sys.stdout.write(text)
    if args.output:
        args.output.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
