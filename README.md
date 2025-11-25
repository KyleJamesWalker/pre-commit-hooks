# Pre Commit Hooks

This repository contains some pre-commit hooks for use with [pre-commit](https://pre-commit.com/).

#### `todo` / 'regex'
Ensures that TODO comments are removed, using the python re module to match lines.
  - `--search-pattern <pattern>` - Change the default grep pattern. The default looks for a
    ticket number directly after the TODO with: `^.*TODO:(?!\s*\[?[A-Z]{1,5}-\d+).*$`.
  - `--repo-skip-pattern <pattern>` - Skip the checks when the repo name matches the
    pattern, useful when allowing TODO comments in a `Template` repo.
    Default: `.*-template-.*`
  - `--found-message` - Allow custom message when search-pattern is found (allows
    generalization for basic regex).

#### `sidecar`
Ensures that sidecar file are up to date.
  - `--sidecar=<primary>:<sidecar>` - Fail if the commit for the `primary` file does not
    include the `sidecar` file.
  - `--age=<sidecar>:<age>` - Fail if the `sidecar` file is older than the specified age.
    The age is a string formatted with: `30d5h`.
    Note the following units are supported:
    - `s` (seconds)
    - `m` (minutes)
    - `h` (hours)
    - `d` (days)
    - `w` (weeks)
    - `M` (months)
    - `y` (years)

#### `check_decorator_kwargs`
Ensures that Python decorators include required keyword arguments. This hook checks
function decorators against a configuration to verify that all specified required
keyword arguments are present.

  - `--config <config>` - Decorator configuration. Can be provided as:
    - JSON string: `'{"task.kubernetes": ["name"], "other.decorator": ["arg1", "arg2"]}'`
    - JSON file path: Path to a JSON file with the same structure
    - Simple format: `'task.kubernetes:name;other.decorator:arg1,arg2'`

    If not provided, the hook checks the `DECORATOR_CHECK_CONFIG` environment variable.
    If neither is provided, defaults to checking `task.kubernetes` for `name` argument.

  Examples:
    - JSON: `--config '{"task.kubernetes": ["name"]}'`
    - Simple: `--config 'task.kubernetes:name;task.docker:image,name'`
    - Environment variable: `DECORATOR_CHECK_CONFIG='{"task.kubernetes": ["name"]}'`

# Development
To develop and test the hooks, you can use the `pre-commit try-repo` command, from
another repo using these hooks. For example:

```bash
PRE_COMMIT_TRY_ARGS="--sidecar=pyproject.toml:poetry.lock --age=poetry.lock:30d" \
pre-commit try-repo ../pre-commit-hooks generated-sidecar
```
