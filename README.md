# Pre Commit Hooks

This repository contains some pre-commit hooks for use with [pre-commit](https://pre-commit.com/).

## Warn-only mode

Hooks block by default. A hook that also supports `--warn-only` reports its
findings and exits 0, so a repository can adopt a check on content it did not
write before the backlog is clean.

The convention for every hook here:

- `--warn-only` downgrades **findings** to warnings and exits 0. A configuration
  or usage error still fails, because a misconfigured hook is not a warning.
- Warning output says `WARN`, never `FAIL`. A report that says both on one screen
  leaves the reader guessing which half to believe.
- Pair it with pre-commit's `verbose: true`. Pre-commit hides the output of a
  passing hook, and a warn-only hook always passes, so without `verbose` the
  warnings are never shown.

Supported by `todo` / `regex` and by both `prose-lint` hooks. Pass the flag
yourself:

```yaml
-   id: prose-lint
    args: [--warn-only]
    verbose: true
```

`prose-lint` also ships ready-made warn ids, `prose-lint-warn` and
`prose-lint-comments-warn`, which set the flag and `verbose` for you.

A useful pairing is to block on what a team controls and warn on the rest:

```yaml
-   id: prose-lint-comments        # blocks: comments are written here
-   id: prose-lint-warn           # warns: inherited documentation
    files: ^docs/
```

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

Language agnostic. Four hook ids share one script:

- `prose-lint` lints documentation files whole (`.md`, `.rst`, `.txt`, and more).
- `prose-lint-comments` lints only the comments and docstrings in source files,
  across roughly 60 extensions. It never scores code, identifiers or string
  literals, so it skips a quoted `"// not a comment"` and a URL containing `#`.
- `prose-lint-warn` and `prose-lint-comments-warn` run the same checks and report
  without blocking. See [Warn-only mode](#warn-only-mode).

Which to pick depends on how much prose the repository already carries. Measured
across 17 repositories, a service or template repo has almost no documentation in
a typical commit, so the blocking ids cost nothing. A documentation-heavy repo is
the opposite case: start on the warn ids, clear the backlog, then switch.

The hook picks comment syntax from the file extension: `#`, `//`, `/* */`, `--`,
`;`, `%`, `<!-- -->`, `<# #>`, plus Python docstrings and Ruby `=begin` blocks.
It drops javadoc ornament (`*`) and machine-readable directives (`@param`,
`# noqa`, `Args:`) before linting. It also rejoins consecutive comment lines, so
it measures a sentence wrapped across several of them as one sentence.

Detection is heuristic, not a parser. It handles line and block comments, string
literals with backslash escapes, and triple-quoted strings. It does not attempt
nested block comments or interpolated expressions inside template strings.

The document profiles mirror the `technical-writing` skill's linter, which is the
source of truth for the rule lists, the thresholds, the 100-word floor and the
short-doc allowance. Two tools disagreeing about one document is its own problem,
so every default here matches it. The `comments` profile has no counterpart in the
skill and is documented on its own terms below.

**Enforcement.** Every finding carries a weight, and every check defaults to 1.0,
so the score is a plain violation count per 100 words. Re-weight a check to make
it advisory or to make it count double. A file fails when any mechanism trips:

- **threshold** — weighted violations per 100 words, for prose at or above
  `min_words`. This puts long and short prose on the same scale.
- **short-doc rule** — below `min_words` a rate is meaningless, so the absolute
  violation count applies instead. See below.
- **max** — an absolute count for a check, for zero tolerance regardless of length.

Below `min_words` a rate says more about length than about quality. At the default
threshold of 2.0, prose gets 50 words of runway per allowed violation. One defect
then passes at 52 words and fails at 45. A 50-word index page with two defects
scores 4.00, which ranks it below a 2000-word document at 3.56.

The short-doc rule counts violations against `short_allowance` instead, and
reports no rate. The two mechanisms agree at the handover. Under `docs` defaults
one violation passes at every length, and two violations fail below 100 words,
where the rate itself starts to allow them.

An allowance of 1 was chosen over the alternatives. Zero lets a single `don't`
gate a commit. Two means nothing short can realistically fail, so the check stops
catching anything. A denominator floor was rejected on purpose: it reports a rate
that was never measured, and a reader seeing 1.0 on a 23-word file would infer
0.23 violations.

The `comments` profile sets `short_allowance` to `null`, which disables the rule
and leaves only the per-check caps. A count rule on a terse comment would cap the
banned-word list by the back door. The rate-based split below exists to prevent
exactly that.

The `comments` profile caps marketing words, hedges and empty closers at zero.
One of those in a comment is worth flagging however short the comment is. The
banned-word list stays rate-based there, because it spans two different things.
`utilize` is clear slop. `ensure` reads as ordinary English in a docstring. An
absolute cap would fail normal code on its first commit.

**Profiles** set the starting point. Configuration resolves in three layers:
profile, then `--config`, then command-line flags.

  | Profile | For | Checks | Threshold | Sentence cap | Short doc |
  |---|---|---|---|---|---|
  | `docs` (default) | READMEs, design docs, guides | 12, no intensifier | 2.0 | 25 words | under 100 words, max 1 |
  | `strict` | runbooks, procedures, error text | all 13 | 0.5 | 20 words | under 100 words, max 0 |
  | `comments` | source-code comments | 4 high-signal | 2.0 | 30 words | rule disabled |

`docs` leaves `intensifier` off, matching the skill: `significantly` and `highly`
carry real meaning in a design doc, and the relaxed word list is what lets standard
prose keep its range. `strict` turns it on.

**Options**
  - `--profile <docs|strict|comments>` - rule preset. Default: `docs`.
  - `--config <config>` - JSON configuration, as a file path or an inline string.
  - `--threshold <number>` - maximum weighted violations per 100 words.
  - `--min-words <n>` - below this word count the short-doc rule applies instead
    of the rate, because a rate is noise on very short prose. Defaults: 100
    (`docs`), 100 (`strict`), 40 (`comments`).
  - `--short-allowance <n>` - violations tolerated below `--min-words`. Defaults:
    1 (`docs`), 0 (`strict`), disabled for `comments`. Set it to `null` in a JSON
    config to disable the rule and leave only the per-check caps.
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
    Emits a list of one object per file.
  - `--total` - add a corpus rollup across every file in the run: word count,
    failing count, short-document count, pooled score, longest sentence and the
    share each check contributes. The pooled score comes from the total weight over the total word
    count, so a long file counts for more than a three-line one. Use it to tell
    whether a corpus has a padding problem or a sentence-length problem. With
    `--json` the top level becomes `{"files": [...], "total": {...}}`.
  - `--list-checks` - print every check with its default weight and profiles.

**Checks**: `long_sentence`, `long_paragraph`, `semicolon`, `contraction`,
`passive_voice`, `ing_main_verb`, `nominalization`, `phrasal_verb`,
`banned_word`, `marketing_adjective`, `hedge`, `intensifier`, `empty_closer`.
Run `--list-checks` for default weights.

Four checks carry exemptions, because the rule they state is not the rule a
reader wants applied everywhere:

  - `semicolon` skips headings, table cells and list items without terminal
    punctuation. Its fix is "write two sentences", and none of those three has
    room for two. `TL;DR` is one token.
  - `passive_voice` skips predicate adjectives such as `is needed` and
    `is unchanged`, where naming an actor produces a worse sentence.
  - `ing_main_verb` skips participles that report a state, such as
    `is running` and `is missing`.
  - `nominalization` skips concrete nouns that merely end in a nominalising
    suffix, such as `the location of`, and requires `perform` and `conduct` to
    carry a nominalised object.

Use `--allow WORD` to drop a single word from the banned and marketing lists,
and the JSON config to re-weight or disable a whole check.

**JSON config format**
```json
{
  "profile": "docs",
  "threshold": 2.0,
  "min_words": 100,
  "short_allowance": 1,
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

**Suppression**. The linter skips inline code, so put a literal value copied from
another system in backticks: `` `Won't Do` ``, `` `PENDING_REVIEW` ``. That is
data, not your prose, and fencing it exempts it from every check while also being
more accurate. Reach for a marker only when the prose itself has to break a rule.

To exempt prose that must quote bad writing, use a marker in a comment. The
single-line form covers the whole paragraph it appears in, because a sentence can
wrap across several lines.

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

`prose_lint.py` has a test suite. Run it from the repository root with the
standard library alone:

```bash
python3 -m unittest discover -s tests -v
```

`tests/test_prose_lint.py` pins current behaviour, including a golden document
checked check by check. A rule change is expected to move those numbers: update
them in the same commit, so the diff shows what the change did to the score.

To develop and test the hooks, you can use the `pre-commit try-repo` command, from
another repo using these hooks. For example:

```bash
PRE_COMMIT_TRY_ARGS="--sidecar=pyproject.toml:poetry.lock --age=poetry.lock:30d" \
pre-commit try-repo ../pre-commit-hooks generated-sidecar
```
