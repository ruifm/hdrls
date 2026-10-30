# hdrls

List the headers that an upstream C/C++ project includes directly.

`hdrls` clones a git repository and asks an LLM (through OpenRouter) for a
minimal `ubuntu:24.04` podman build environment and build commands. It builds
the project under `bear`. When a step fails, it sends the log to the LLM and
tries the corrected plan. After a successful build, it adds `-H -fsyntax-only`
to each compile command, runs each command in the build container, and prints
a sorted, deduplicated list of the depth-1 includes of all translation units.

## Requirements

- Python 3.12 or later, `uv`, `git`, rootless `podman`.
- `OPENROUTER_API_KEY` in the environment.

## Usage

```
uv run hdrls https://github.com/madler/zlib --output /tmp/zlib-headers.txt
```

Options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--model` | `anthropic/claude-sonnet-4.5` | OpenRouter model id |
| `--max-attempts` | `5` | LLM plans to try, first plan included |
| `--workdir` | `~/.cache/hdrls/<name>-<hash>` | Clone, logs, and outputs |
| `--build-timeout` | `3600` | Seconds for each build attempt |
| `--output` | none | Also write the list to this file |

Output paths are paths in the container: the repository is at `/src`, and
system headers are paths in the build image.

Exit codes: `0` success; `1` the build did not succeed, or every header
command failed; `2` configuration, clone, or HTTP error.

## Work directory

- `src/` — the clone. It is reused on the next run.
- `out/compile_commands.json` — the database that `bear` recorded.
- `out/compile_commands.headers.json` — the same commands with `-H -fsyntax-only`.
- `logs/attempt-<n>-<stage>.log` — the log of each failed attempt. The stages
  are `invalid-json`, `image-build`, `build`, and `empty-compdb`.
- `plan.json` — the accepted build plan.

## Tests

```
uv run pytest -q
```

`tests/test_e2e.py` needs `podman` and network access to pull `ubuntu:24.04`.
It uses a fake LLM, so it does not need an API key.
