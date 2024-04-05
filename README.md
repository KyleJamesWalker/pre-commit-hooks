# Pre Commit Hooks

This repository contains some pre-commit hooks for use with [pre-commit](https://pre-commit.com/).

#### `todo`
Ensures that TODO comments are removed, using the python re module to match lines.
  - `--search-pattern <pattern>` - Change the default grep pattern. The default looks for a
    ticket number directly after the TODO with: `^.*TODO:(?!\s*\[?[A-Z]{1,5}-\d+).*$`.
  - `--repo-skip-pattern <pattern>` - Skip the checks when the repo name matches the
    pattern, useful when allowing TODO comments in a `Template` repo.
    Default: `.*-template-.*`

#### `sidecar`
Ensures that sidecar file are up to date.

# Development
To develop and test the hooks, you can use the `pre-commit try-repo` command, from
another repo using these hooks. For example:

```bash
PRE_COMMIT_TRY_ARGS="--sidecar=pyproject.toml:poetry.lock --age=poetry.lock:30d" \
pre-commit try-repo ../pre-commit-hooks generated-sidecar
```
