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
  - `--warn-only` - Report matches as warnings and exit 0 instead of failing. Also
    scans repos matching `--repo-skip-pattern`, so a `Template` repo can surface the
    TODOs that will start blocking once the hook enforces normally (pair with
    pre-commit's `verbose: true` so the warnings show on a passing run).

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

#### `prose-lint` / `prose-lint-comments`
Lints prose against the machine-checkable subset of
[ASD-STE100](https://asd-ste100.org) Simplified Technical English: word choice,
sentence length, voice, hedging, marketing language and paragraph size.

Language agnostic. Two hook ids share one script:

- `prose-lint` lints documentation files whole (`.md`, `.rst`, `.txt`, and more).
- `prose-lint-comments` lints only the comments and docstrings in source files,
  across roughly 60 extensions. It never scores code, identifiers or string
  literals, so it skips a quoted `"// not a comment"` and a URL containing `#`.

The hook picks comment syntax from the file extension: `#`, `//`, `/* */`, `--`,
`;`, `%`, `<!-- -->`, `<# #>`, plus Python docstrings and Ruby `=begin` blocks.
It drops javadoc ornament (`*`) and machine-readable directives (`@param`,
`# noqa`, `Args:`) before linting. It also rejoins consecutive comment lines, so
it measures a sentence wrapped across several of them as one sentence.

Detection is heuristic, not a parser. It handles line and block comments, string
literals with backslash escapes, and triple-quoted strings. It does not attempt
nested block comments or interpolated expressions inside template strings.

**Enforcement.** Every finding carries a weight. A file fails when either
mechanism trips:

- **threshold** — weighted violations per 100 words. This puts long and short
  prose on the same scale.
- **max** — an absolute count for a check, for zero tolerance regardless of length.

The `comments` profile caps marketing words, hedges and empty closers at zero.
One of those in a comment is worth flagging however short the comment is. The
banned-word list stays rate-based there, because it spans two different things.
`utilize` is clear slop. `ensure` reads as ordinary English in a docstring. An
absolute cap would fail normal code on its first commit.

**Profiles** set the starting point. Configuration resolves in three layers:
profile, then `--config`, then command-line flags.

  | Profile | For | Checks | Threshold | Sentence cap |
  |---|---|---|---|---|
  | `docs` (default) | READMEs, design docs, guides | all 13 | 2.0 | 25 words |
  | `strict` | runbooks, procedures, error text | all 13 | 0.5 | 20 words |
  | `comments` | source-code comments | 4 high-signal | 2.0 | 30 words |

**Options**
  - `--profile <docs|strict|comments>` - rule preset. Default: `docs`.
  - `--config <config>` - JSON configuration, as a file path or an inline string.
  - `--threshold <number>` - maximum weighted violations per 100 words.
  - `--min-words <n>` - below this word count only absolute caps apply, because a
    rate is noise on very short prose. Defaults: 50 (`docs`), 30 (`strict`),
    40 (`comments`).
  - `--max-sentence-words <n>` / `--max-paragraph-sentences <n>` - length caps.
    Set the paragraph cap to `0` to disable it.
  - `--enable <check>` / `--disable <check>` - toggle one check. Repeatable.
  - `--weight <check>=<number>` - re-weight one check. Repeatable.
  - `--max <check>=<integer>` - absolute cap for one check. Repeatable.
  - `--allow <word>` - drop a word from the banned and marketing lists, for a
    project where it is a domain term. Repeatable.
  - `--exclude <glob>` - skip matching paths. Repeatable.
  - `--include-unknown` - treat extensionless files as documentation.
  - `--warn-only` - report findings and exit 0, matching the `todo` hook. Pair
    with pre-commit's `verbose: true` so warnings show on a passing run.
  - `--quiet` - omit the quoted excerpt under each finding.
  - `--json` - machine-readable results, for reporting or a CI budget check.
  - `--list-checks` - print every check with its default weight and profiles.

**Checks**: `long_sentence`, `long_paragraph`, `semicolon`, `contraction`,
`passive_voice`, `ing_main_verb`, `nominalization`, `phrasal_verb`,
`banned_word`, `marketing_adjective`, `hedge`, `intensifier`, `empty_closer`.
Run `--list-checks` for default weights.

**JSON config format**
```json
{
  "profile": "docs",
  "threshold": 2.0,
  "min_words": 50,
  "max_sentence_words": 25,
  "max_paragraph_sentences": 6,
  "checks": {
    "marketing_adjective": {"weight": 3.0, "max": 0},
    "passive_voice": {"enabled": false}
  },
  "allow": ["ensure"],
  "extra_banned": {"k8s": "Kubernetes"},
  "extra_marketing": ["synergy"]
}
```

Keys are optional. `checks` accepts `enabled`, `weight` and `max` per check.
`allow` removes words from the defaults, `extra_banned` and `extra_marketing`
add project-specific ones.

**Suppression**. To exempt prose that must quote bad writing, use a marker in a
comment. The single-line form covers the whole paragraph it appears in, because a
sentence can wrap across several lines.

```markdown
This paragraph quotes a bad example. <!-- prose-lint: ignore -->

<!-- prose-lint: ignore-start -->
Everything here is skipped.
<!-- prose-lint: ignore-end -->
```

In source files use the language's comment syntax, for example
`# prose-lint: ignore` or `// prose-lint: ignore-start`.

**Exit codes**: `0` pass, `1` prose over budget, `2` bad configuration or an
unreadable file.

Examples:
  - Documentation, default budget:
    ```yaml
    -   id: prose-lint
    ```
  - Runbooks under a stricter budget, docs under the normal one:
    ```yaml
    -   id: prose-lint
        args: [--profile, strict]
        files: ^runbooks/
    -   id: prose-lint
        files: ^docs/
    ```
  - Comments, warning only at first, with a project term allowed:
    ```yaml
    -   id: prose-lint-comments
        args: [--warn-only, --allow, leverage]
        verbose: true
    ```
  - Shared config file, checked into the repo:
    ```yaml
    -   id: prose-lint
        args: [--config, .prose-lint.json]
    ```

# Development
To develop and test the hooks, you can use the `pre-commit try-repo` command, from
another repo using these hooks. For example:

```bash
PRE_COMMIT_TRY_ARGS="--sidecar=pyproject.toml:poetry.lock --age=poetry.lock:30d" \
pre-commit try-repo ../pre-commit-hooks generated-sidecar
```
