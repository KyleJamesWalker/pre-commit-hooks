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

#### `generated-sidecar`
Ensures that sidecar file are up to date.
  - `--sidecar=<primary>:<sidecar>` - Fail if the commit for the `primary` file does not
    include the `sidecar` file.
  - `--age=<file>:<age>[:<source>]` - Fail if the `file` is older than the specified age.
    The age is a string formatted with: `30d5h`.
    Note the following units are supported:
    - `s` (seconds)
    - `m` (minutes)
    - `h` (hours)
    - `d` (days)
    - `w` (weeks)
    - `M` (months)
    - `y` (years)

    The optional `source` controls how file age is determined:
    - `commit` (default) — uses `git log` to find the last commit time. This works
      correctly on freshly cloned repos where filesystem timestamps are all recent.
    - `mtime` — uses the filesystem modification time.

    Examples:
    - `--age=poetry.lock:30d` — fails if poetry.lock was last committed over 30 days ago
    - `--age=poetry.lock:30d:commit` — same as above (explicit)
    - `--age=poetry.lock:30d:mtime` — uses filesystem modification time instead

#### `decorator-kwargs`
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

#### `yaml-sync`
Validates that two or more YAML files are synchronized according to configurable rules.
This hook can validate any YAML structure and supports both JSON configuration files
and simple command-line arguments. Files are specified as pairs of `(file_path yaml_path)`,
and the script validates all pairs of files to ensure they are synchronized.

  - `--config <config>` - JSON configuration. Can be provided as:
    - JSON file path: Path to a JSON file with validation rules
    - JSON string: `'{"rules": [{"keys": ["IMAGE"], "type": "tag_match"}]}'`

    The JSON config format:
    ```json
    {
      "rules": [
        {
          "keys": ["IMAGE"],
          "type": "tag_match"
        },
        {
          "keys": ["*"],
          "type": "exact_match"
        },
        {
          "keys": ["VERSION"],
          "type": "regex_match",
          "pattern": "v(\\d+\\.\\d+)",
          "extract_group": 1
        },
        {
          "keys": ["ENV"],
          "type": "no_validation"
        }
      ]
    }
    ```

  - `--tag-match=<keys>` - Comma-separated keys that must have matching image tags
    (e.g., `IMAGE`). Extracts and compares only the tag portion after the colon.
    Can be specified multiple times.

  - `--exact-match=<keys>` - Comma-separated keys that must match exactly
    (e.g., `KEY1,KEY2` or `*` for all keys). Can be specified multiple times.

  - `--regex-match=<rule>` - Regex match rule in format `KEYS:PATTERN[:GROUP]`
    (e.g., `VERSION:v(\\d+\\.\\d+):1`). The pattern is applied to both values, and
    if `GROUP` is specified (default 0), that capture group is extracted and compared.
    Can be specified multiple times.

  - `--no-validation=<keys>` - Comma-separated keys to skip validation
    (e.g., `KEY1,KEY2`). Can be specified multiple times.

  **File format**: Files are specified as pairs of `(file_path yaml_path)` where:
    - `file_path` is the path to the YAML file
    - `yaml_path` is a dot-notation path to the data within the YAML (e.g., `configMapData`,
      `data`, `spec.template.spec.containers[0].env`). Use empty string `""` for root level.
      Supports array indexing like `containers[0]`.

  **Validation rules**:
    - `tag_match`: Extracts and compares image tags (e.g., `"image:tag"` → compares `"tag"`)
    - `exact_match`: Values must be exactly equal
    - `regex_match`: Values must match a regex pattern (can extract groups for comparison)
    - `no_validation`: Skip validation (allow any differences)

  **Key matching**: Keys are matched to the first rule that includes them. Use `*` as a
  wildcard to match all remaining keys. All keys must be matched by at least one rule.

  **Multiple files**: When multiple files are provided, all pairs of files are validated
  to ensure they're all synchronized.

  Examples:
    - Simple args with two files:
      ```
      file1.yaml "" file2.yaml "" --tag-match=IMAGE --exact-match=*
      ```

    - JSON config with nested paths:
      ```
      file1.yaml "spec.template.spec.containers[0].env" file2.yaml "data" --config rules.json
      ```

    - Multiple files with regex:
      ```
      file1.yaml "" file2.yaml "" file3.yaml "" --regex-match="VERSION:v(\\d+):1" --exact-match=*
      ```

    - JSON string inline:
      ```
      file1.yaml "" file2.yaml "" --config '{"rules": [{"keys": ["*"], "type": "exact_match"}]}'
      ```

# Development
To develop and test the hooks, you can use the `pre-commit try-repo` command, from
another repo using these hooks. For example:

```bash
PRE_COMMIT_TRY_ARGS="--sidecar=pyproject.toml:poetry.lock --age=poetry.lock:30d" \
pre-commit try-repo ../pre-commit-hooks generated-sidecar
```
