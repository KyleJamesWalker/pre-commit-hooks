#!/usr/bin/env python3
"""Baseline tests for prose_lint.py.

Run with the standard library alone, from the repository root:

    python3 -m unittest discover -s tests -v

The suite is a baseline in the literal sense: it pins current behaviour so that a
later rule change shows up as an intentional diff rather than as silent drift.
prose_lint.py is 1000+ lines of regex-dense heuristics whose output every repo in
the organisation is scored against, so an unreviewed shift in any word list moves
every score at once.

Every fixture here is synthetic and generic. Nothing depends on a real repository,
a real document or a company-specific term, because a test that reads a file
outside this repository fails for reasons that have nothing to do with the linter.

Layout, in the order a reader should meet it:

    ExitCodeTests            the 0/1/2 contract the hook and README promise
    ThresholdTests           the rate, the short-document rule and the caps
    ConfigTests              profile -> JSON -> CLI layering, vocabulary edits
    SuppressionTests         ignore markers, fenced code, frontmatter
    DocumentExtractionTests  which markdown is prose and which is structure
    CommentExtractionTests   the per-language comment and docstring tables
    PythonExtractionTests    docstrings via ast, comments via tokenize
    DirectiveTests           tool directives versus documentation tags
    LineAttributionTests     a finding names the line holding its text
    PerformanceTests         a guard against the O(n^2) excerpt regression
    HostileInputTests        empty, CRLF, unterminated, unreadable
    GoldenTests              a pinned document, checked whole
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import prose_lint  # noqa: E402

LINT = os.path.join(ROOT, "prose_lint.py")

# Clean filler used to push a fixture over the 100-word floor without adding a
# violation. Kept deliberately dull: any word here that later joins a rule list
# would turn every threshold test into a false failure.
FILLER = (
    "The parser reads one record at a time. The writer stores each record. "
    "The reader returns the next record. The queue holds the pending records. "
    "The worker takes a record from the queue. The log keeps one line per record. "
    "The report counts the records. The cache holds the recent records. "
    "The index maps a key to a record. The server sends the record to the client. "
)


def filler_words(count):
    """Return at least `count` words of violation-free prose, in paragraphs.

    The paragraph breaks are not decoration. Six sentences in one block trips
    long_paragraph, so filler written as a single block would fail every
    threshold fixture for a reason the fixture was not testing.
    """
    pool = [s.strip() for s in (FILLER * (count // 40 + 2)).split(".") if s.strip()]
    paragraphs, current, total = [], [], 0
    for sentence in pool:
        current.append(sentence + ".")
        total += len(sentence.split())
        if len(current) == 3:
            paragraphs.append(" ".join(current))
            current = []
        if total >= count and not current:
            break
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


class Harness(unittest.TestCase):
    """Shared helpers. Every test drives the real command line."""

    def write(self, name, text):
        """Write a fixture into a per-test temporary directory."""
        if not hasattr(self, "_dir"):
            self._dir = tempfile.mkdtemp(prefix="prose-lint-test-")
            self.addCleanup(self._cleanup)
        path = os.path.join(self._dir, name)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def write_bytes(self, name, payload):
        """Write a fixture that is deliberately not valid UTF-8 text."""
        path = self.write(name, "")
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def _cleanup(self):
        for root, dirs, files in os.walk(self._dir, topdown=False):
            for name in files:
                os.unlink(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(self._dir)

    def run_lint(self, *args):
        """Run the hook as a subprocess. Returns (exit code, stdout, stderr)."""
        proc = subprocess.run([sys.executable, LINT] + list(args),
                              capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    def evaluate(self, *args):
        """Run the hook with --json and return the single file result."""
        code, out, err = self.run_lint("--json", *args)
        self.assertNotEqual(code, 2, "configuration error: %s" % err)
        payload = json.loads(out)
        self.assertEqual(len(payload), 1, "expected exactly one result")
        return payload[0]

    def checks(self, *args):
        """Return {check name: count} for one file."""
        return self.evaluate(*args)["counts"]

    def lines_for(self, check, *args):
        """Return the reported line numbers for one check, in order."""
        return [f["line"] for f in self.evaluate(*args)["findings"]
                if f["check"] == check]


class ExitCodeTests(Harness):
    """0 means clean, 1 means over budget, 2 means the run was misconfigured.

    The distinction matters more than it looks: a caller that cannot tell a
    misconfigured hook from failing prose reports a typo in its own YAML as an
    author's writing problem.
    """

    def test_clean_document_exits_zero(self):
        path = self.write("clean.md", "# Title\n\n%s\n" % filler_words(120))
        self.assertEqual(self.run_lint(path)[0], 0)

    def test_document_over_budget_exits_one(self):
        text = "# Title\n\nWe utilize the seamless robust approach.\n\n%s\n" % filler_words(40)
        path = self.write("bad.md", text)
        self.assertEqual(self.run_lint(path)[0], 1)

    def test_warn_only_exits_zero_while_still_reporting(self):
        text = "# Title\n\nWe utilize the seamless robust approach.\n"
        path = self.write("warn.md", text)
        code, _, err = self.run_lint("--warn-only", path)
        self.assertEqual(code, 0)
        self.assertIn("utilize", err)
        self.assertIn("not blocking", err)

    def test_unknown_profile_exits_two(self):
        path = self.write("doc.md", "# Title\n")
        self.assertEqual(self.run_lint("--profile", "nope", path)[0], 2)

    def test_unreadable_paths_exit_two(self):
        missing = os.path.join(tempfile.gettempdir(), "prose-lint-absent.md")
        self.assertEqual(self.run_lint(missing)[0], 2)
        # A directory only reaches the reader if its name classifies as prose.
        self.write("doc.md", "# Title\n")
        as_dir = os.path.join(self._dir, "folder.md")
        os.makedirs(as_dir)
        self.assertEqual(self.run_lint(as_dir)[0], 2)

    def test_malformed_json_config_exits_two(self):
        path = self.write("doc.md", "# Title\n")
        self.assertEqual(self.run_lint("--config", "{not json", path)[0], 2)
        self.assertEqual(self.run_lint("--config", "[1, 2]", path)[0], 2)

    def test_unknown_check_name_exits_two(self):
        path = self.write("doc.md", "# Title\n")
        for flag in ("--enable", "--disable"):
            self.assertEqual(self.run_lint(flag, "nosuchcheck", path)[0], 2)
        self.assertEqual(self.run_lint("--weight", "nosuchcheck=2", path)[0], 2)

    def test_non_numeric_config_values_exit_two(self):
        """A bad number is a configuration error, not failing prose.

        These four exited 1 with an uncaught ValueError traceback before the
        conversions were routed through a configuration error.
        """
        path = self.write("doc.md", "# Title\n")
        cases = [
            ("--weight", "semicolon=bar"),
            ("--max", "semicolon=1.5"),
            ("--threshold", "nope"),
            ("--min-words", "nope"),
        ]
        for flag, value in cases:
            code, _, err = self.run_lint(flag, value, path)
            self.assertEqual(code, 2, "%s %s should exit 2, got %d" % (flag, value, code))
            self.assertNotIn("Traceback", err)
        for blob in ('{"checks": {"semicolon": {"weight": "bar"}}}',
                     '{"checks": {"semicolon": {"max": "bar"}}}'):
            code, _, err = self.run_lint("--config", blob, path)
            self.assertEqual(code, 2)
            self.assertNotIn("Traceback", err)


class ThresholdTests(Harness):
    """The three enforcement mechanisms, and the handover between them."""

    def test_rate_applies_at_or_above_the_word_floor(self):
        """At or above the floor the verdict is a rate, and the rate is reported."""
        text = "# Title\n\nWe utilize the approach.\n\n%s\n" % filler_words(110)
        result = self.evaluate(self.write("rate.md", text))
        self.assertFalse(result["is_short"])
        self.assertGreater(result["rate"], 0.0)
        self.assertTrue(result["passed"], "one violation in 110 words is under budget")

    def test_long_document_fails_once_the_rate_passes_the_threshold(self):
        slop = "We utilize and leverage and obtain and facilitate this. "
        text = "# Title\n\n%s\n\n%s\n" % (slop, filler_words(110))
        result = self.evaluate(self.write("overrate.md", text))
        self.assertFalse(result["is_short"])
        self.assertFalse(result["passed"])
        self.assertIn("per 100 words", " ".join(result["reasons"]))

    def test_short_document_is_judged_on_count_and_reports_no_rate(self):
        """Below the floor a rate says more about length than about quality."""
        path = self.write("short.md", "# Title\n\nWe utilize the approach.\n")
        result = self.evaluate(path)
        self.assertTrue(result["is_short"])
        self.assertTrue(result["passed"], "one violation is within the allowance")
        self.assertEqual(result["reasons"], [])

    def test_short_document_fails_on_the_second_violation(self):
        path = self.write("short2.md", "# Title\n\nWe utilize and leverage it.\n")
        result = self.evaluate(path)
        self.assertTrue(result["is_short"])
        self.assertFalse(result["passed"])
        self.assertIn("short-doc rule", " ".join(result["reasons"]))

    def test_short_allowance_of_zero_fails_a_single_violation(self):
        path = self.write("strict.md", "# Title\n\nWe utilize the approach.\n")
        result = self.evaluate("--short-allowance", "0", path)
        self.assertFalse(result["passed"])

    def test_null_short_allowance_leaves_only_the_caps(self):
        """The comments profile disables the count rule on purpose.

        A count rule on a short comment would put every rate-based check back
        under an absolute cap by the back door.
        """
        path = self.write("mod.py", '"""We utilize and leverage and obtain it."""\n')
        result = self.evaluate("--profile", "comments", path)
        self.assertTrue(result["is_short"])
        self.assertIsNone(result["short_allowance"])
        self.assertTrue(result["passed"])

    def test_absolute_cap_fails_independently_of_the_rate(self):
        text = '"""This is a seamless approach."""\n'
        path = self.write("cap.py", text)
        result = self.evaluate("--profile", "comments", path)
        self.assertFalse(result["passed"])
        self.assertIn("marketing_adjective", " ".join(result["reasons"]))

    def test_sentence_and_paragraph_caps_are_configurable(self):
        sentence = "The parser reads " + " ".join(["one"] * 30) + " record.\n"
        path = self.write("sent.md", "# Title\n\n%s" % sentence)
        self.assertEqual(self.checks(path).get("long_sentence", 0), 1)
        self.assertEqual(
            self.checks("--max-sentence-words", "60", path).get("long_sentence", 0), 0)

    def test_paragraph_cap_counts_sentences_not_lines(self):
        body = " ".join("The parser reads record %d." % n for n in range(8))
        path = self.write("para.md", "# Title\n\n%s\n" % body)
        self.assertEqual(self.checks(path).get("long_paragraph", 0), 1)
        self.assertEqual(
            self.checks("--max-paragraph-sentences", "20", path).get("long_paragraph", 0), 0)

    def test_headings_and_table_cells_are_not_sentences(self):
        """Both are fragments, so neither carries a sentence-length verdict."""
        heading = "# " + " ".join(["word"] * 40) + "\n"
        row = "| " + " ".join(["word"] * 40) + " |\n"
        path = self.write("frag.md", heading + "\n" + row)
        self.assertEqual(self.checks(path).get("long_sentence", 0), 0)


class ConfigTests(Harness):
    """Profile, then JSON, then command line, each overriding the last."""

    def test_command_line_beats_json_config(self):
        text = "# Title\n\nWe utilize the approach.\n\n%s\n" % filler_words(110)
        path = self.write("doc.md", text)
        self.assertTrue(self.evaluate("--config", '{"threshold": 9.0}', path)["passed"])
        # The command line wins, so the generous JSON threshold does not apply.
        self.assertFalse(self.evaluate("--config", '{"threshold": 9.0}',
                                       "--threshold", "0.1", path)["passed"])

    def test_json_config_beats_the_profile(self):
        path = self.write("doc.md", "# Title\n")
        result = self.evaluate("--config", '{"min_words": 1}', path)
        self.assertFalse(result["is_short"])

    def test_disable_wins_over_enable_for_the_same_check(self):
        path = self.write("doc.md", "# Title\n\nIt is very fast.\n")
        counts = self.checks("--enable", "intensifier", "--disable", "intensifier", path)
        self.assertEqual(counts.get("intensifier", 0), 0)

    def test_allow_removes_a_word_from_both_lists(self):
        path = self.write("doc.md", "# Title\n\nWe utilize the seamless approach.\n")
        counts = self.checks("--allow", "utilize", "--allow", "seamless", path)
        self.assertEqual(counts.get("banned_word", 0), 0)
        self.assertEqual(counts.get("marketing_adjective", 0), 0)

    def test_project_vocabulary_can_be_extended(self):
        path = self.write("doc.md", "# Title\n\nThe widget is frobnicated and zesty.\n")
        blob = json.dumps({"extra_banned": {"frobnicated": "processed"},
                           "extra_marketing": ["zesty"]})
        counts = self.checks("--config", blob, path)
        self.assertEqual(counts.get("banned_word", 0), 1)
        self.assertEqual(counts.get("marketing_adjective", 0), 1)

    def test_weight_scales_the_score_without_changing_counts(self):
        text = "# Title\n\nWe utilize the approach.\n\n%s\n" % filler_words(110)
        path = self.write("doc.md", text)
        base = self.evaluate(path)
        heavy = self.evaluate("--weight", "banned_word=4", path)
        self.assertEqual(base["counts"], heavy["counts"])
        self.assertGreater(heavy["rate"], base["rate"])

    def test_exclude_glob_skips_a_path_entirely(self):
        path = self.write("doc.md", "# Title\n\nWe utilize and leverage it.\n")
        code, out, _ = self.run_lint("--json", "--exclude", "*.md", path)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [])

    def test_unsupported_extension_is_skipped(self):
        path = self.write("data.bin", "We utilize the seamless robust approach.\n")
        code, out, _ = self.run_lint("--json", path)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [])

    def test_include_unknown_treats_extensionless_files_as_prose(self):
        """This is what lets the strict profile reach a commit message."""
        path = self.write("COMMIT_EDITMSG", "We utilize the seamless approach.\n")
        code, out, _ = self.run_lint("--json", path)
        self.assertEqual(json.loads(out), [])
        result = self.evaluate("--include-unknown", path)
        self.assertGreater(sum(result["counts"].values()), 0)

    def test_list_checks_names_every_check(self):
        code, out, _ = self.run_lint("--list-checks")
        self.assertEqual(code, 0)
        for name in prose_lint.ALL_CHECKS:
            self.assertIn(name, out)


class SuppressionTests(Harness):
    """Some documents have to quote bad prose. Those need an explicit escape."""

    def test_ignore_marker_covers_the_whole_paragraph(self):
        text = ("# Title\n\nWe utilize the seamless robust approach here and it\n"
                "spans two lines. <!-- prose-lint: ignore -->\n\n%s\n"
                % filler_words(110))
        path = self.write("ig.md", text)
        self.assertEqual(self.checks(path), {})

    def test_ignore_region_covers_every_line_between_the_markers(self):
        text = ("# Title\n\n<!-- prose-lint: ignore-start -->\n"
                "We utilize the seamless approach.\n\nWe leverage the robust one.\n"
                "<!-- prose-lint: ignore-end -->\n\nWe utilize this.\n")
        path = self.write("region.md", text)
        self.assertEqual(self.checks(path).get("banned_word", 0), 1)

    def test_fenced_code_and_inline_code_are_not_prose(self):
        text = ("# Title\n\n```bash\nutilize --seamless --robust\n```\n\n"
                "Use `utilize --robust` at the prompt.\n\n%s\n" % filler_words(110))
        path = self.write("code.md", text)
        self.assertEqual(self.checks(path), {})

    def test_frontmatter_is_configuration_not_prose(self):
        text = ("---\ntitle: We utilize the seamless robust approach\n---\n\n"
                "# Title\n\n%s\n" % filler_words(110))
        path = self.write("fm.md", text)
        self.assertEqual(self.checks(path), {})

    def test_link_targets_and_entities_are_not_prose(self):
        text = ("# Title\n\nSee [the guide](https://example.com/utilize-the-robust)\n"
                "and note the spacing&nbsp;here.\n\n%s\n" % filler_words(110))
        path = self.write("links.md", text)
        counts = self.checks(path)
        self.assertEqual(counts.get("banned_word", 0), 0)
        self.assertEqual(counts.get("semicolon", 0), 0)


class DocumentExtractionTests(Harness):
    """Which markdown constructs carry prose, and which are structure."""

    def test_hard_wrapped_sentence_is_measured_whole(self):
        """A wrapped sentence is one sentence, so its length is one number.

        This is also why a phrase straddling a wrap point is found at all.
        """
        text = "# Title\n\nThe parser is\nupdated by the writer.\n"
        path = self.write("wrap.md", text)
        self.assertEqual(self.checks(path).get("passive_voice", 0), 1)

    def test_list_items_are_separate_units(self):
        text = "# Title\n\n- We utilize this.\n- We leverage that.\n"
        path = self.write("list.md", text)
        self.assertEqual(self.checks(path).get("banned_word", 0), 2)

    def test_admonitions_and_details_blocks_are_prose(self):
        text = ("# Title\n\n> [!NOTE]\n> We utilize the approach.\n\n"
                "<details>\n<summary>More</summary>\n\nWe leverage the other one.\n\n"
                "</details>\n")
        path = self.write("adm.md", text)
        self.assertEqual(self.checks(path).get("banned_word", 0), 2)

    def test_indented_blocks_are_treated_as_code(self):
        text = "# Title\n\n    utilize the seamless robust thing\n\n%s\n" % filler_words(110)
        path = self.write("indent.md", text)
        self.assertEqual(self.checks(path), {})

    def test_every_documentation_extension_is_recognised(self):
        for ext in sorted(prose_lint.DOC_EXTENSIONS):
            path = self.write("doc%s" % ext, "We utilize the approach.\n")
            kind, _ = prose_lint.classify(path, False)
            self.assertEqual(kind, "doc", "%s should be a document" % ext)


class CommentExtractionTests(Harness):
    """Comments and docstrings are prose. Code and string literals are not."""

    def test_hash_slash_dash_and_markup_comments_are_found(self):
        cases = [
            ("mod.sh", "# We utilize the approach.\necho hello\n"),
            ("mod.js", "// We utilize the approach.\nconst a = 1;\n"),
            ("mod.js2.js", "/* We utilize the approach. */\nconst a = 1;\n"),
            ("mod.sql", "-- We utilize the approach.\nSELECT 1;\n"),
            ("page.html", "<!-- We utilize the approach. -->\n<p>hi</p>\n"),
            ("mod.tf", "# We utilize the approach.\nvariable \"a\" {}\n"),
        ]
        for name, text in cases:
            path = self.write(name, text)
            counts = self.checks("--profile", "comments", path)
            self.assertEqual(counts.get("banned_word", 0), 1,
                             "%s: comment prose was not found" % name)

    def test_string_literals_are_not_comments(self):
        text = 'const url = "http://example.com/utilize";\nconst s = "# utilize";\n'
        path = self.write("mod.js", text)
        self.assertEqual(self.evaluate("--profile", "comments", path)["words"], 0)

    def test_contiguous_comment_lines_are_rejoined(self):
        """A phrase split across two comment lines is still one phrase."""
        text = "// We do this in order\n// to make it work.\nconst a = 1;\n"
        path = self.write("mod.js", text)
        self.assertEqual(
            self.checks("--profile", "comments", path).get("banned_word", 0), 1)

    def test_separated_comment_lines_are_not_rejoined(self):
        text = "// We do this in order\nconst a = 1;\n// to make it work.\n"
        path = self.write("mod.js", text)
        self.assertEqual(
            self.checks("--profile", "comments", path).get("banned_word", 0), 0)

    def test_block_comment_ornament_is_stripped(self):
        text = "/*\n * We utilize the approach.\n */\nconst a = 1;\n"
        path = self.write("mod.js", text)
        self.assertEqual(
            self.checks("--profile", "comments", path).get("banned_word", 0), 1)

    def test_comments_profile_enables_only_the_high_signal_checks(self):
        enabled = set(prose_lint.PROFILES["comments"]["enabled"])
        self.assertEqual(enabled, set(prose_lint.HIGH_SIGNAL))


class PythonExtractionTests(Harness):
    """A triple-quoted string is a docstring only where the grammar says so."""

    def test_real_docstrings_are_linted(self):
        text = ('"""We utilize the module approach."""\n\n\n'
                'class Thing(object):\n    """We leverage the class approach."""\n\n'
                '    def go(self):\n        """We obtain the method approach."""\n'
                '        return 1\n')
        path = self.write("mod.py", text)
        self.assertEqual(
            self.checks("--profile", "comments", path).get("banned_word", 0), 3)

    def test_data_in_triple_quotes_is_not_a_docstring(self):
        """A SQL block, a PEM key and an f-string template are data.

        Scoring them invented findings and padded the word count that every rate
        divides by. One real file failed a commit on the word inside
        `b"-----BEGIN PUBLIC KEY-----"`.
        """
        text = (
            'KEY = b"""-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n"""\n'
            'QUERY = """\n    -- We utilize the seamless robust query\n    SELECT 1\n"""\n'
            'STEP = dict(apply="""\n    We leverage the robust migration\n""")\n'
        )
        path = self.write("mod.py", text)
        result = self.evaluate("--profile", "comments", path)
        self.assertEqual(result["words"], 0)
        self.assertEqual(result["counts"], {})
        self.assertTrue(result["passed"])

    def test_comments_are_still_read_alongside_docstrings(self):
        text = '# We utilize the approach.\nX = """not a docstring"""\n'
        path = self.write("mod.py", text)
        self.assertEqual(
            self.checks("--profile", "comments", path).get("banned_word", 0), 1)

    def test_shebang_is_configuration_not_prose(self):
        text = "#!/usr/bin/env python3\nX = 1\n"
        path = self.write("mod.py", text)
        self.assertEqual(self.evaluate("--profile", "comments", path)["words"], 0)

    def test_unparseable_source_falls_back_instead_of_being_skipped(self):
        """A syntax error is a reason to lint less precisely, not to stop."""
        text = 'def broken(:\n    """We utilize the seamless approach."""\n'
        path = self.write("mod.py", text)
        self.assertIsNone(prose_lint.extract_python(text))
        self.assertGreater(
            self.checks("--profile", "comments", path).get("banned_word", 0), 0)


class DirectiveTests(Harness):
    """A tool directive is configuration. A documentation tag labels prose."""

    def test_tool_directives_contribute_no_prose(self):
        for line in ("# noqa: E501 line too long",
                     "# type: ignore[arg-type]",
                     "# pylint: disable=invalid-name",
                     "# ruff: noqa"):
            self.assertEqual(prose_lint.strip_directive(line.lstrip("# ")), "")

    def test_documentation_tags_keep_their_description(self):
        """Dropping the whole line hid the prose the tag introduces."""
        cases = [
            ("@param cfg - We utilize the approach.", "We utilize the approach."),
            ("@returns We leverage the result.", "We leverage the result."),
            ("Note: We obtain the value.", "We obtain the value."),
            ("See: the design document for the rest", "the design document for the rest"),
        ]
        for line, expected in cases:
            self.assertEqual(prose_lint.strip_directive(line), expected)

    def test_command_syntax_after_a_tag_is_not_prose(self):
        """The skill puts command syntax out of scope.

        Counting it pads the word count, which dilutes real findings below the
        threshold rather than adding new ones.
        """
        for line in ("Usage: ./run.sh <ID> [out.json]",
                     "Example: $ curl -sX GET /v1/things",
                     "Example: run.sh --flag value"):
            self.assertEqual(prose_lint.strip_directive(line), "")

    def test_prose_naming_a_flag_is_still_prose(self):
        line = "Note: run with --verbose to see more output when debugging"
        self.assertTrue(prose_lint.strip_directive(line))

    def test_a_bare_address_carries_no_prose(self):
        self.assertEqual(prose_lint.strip_directive("https://example.com/utilize"), "")

    def test_an_all_tagged_comment_block_is_still_scored(self):
        text = ("/**\n * @param a - We utilize the seamless approach.\n"
                " * @returns We leverage the robust result.\n */\n"
                "export function go(a) { return a; }\n")
        path = self.write("mod.js", text)
        result = self.evaluate("--profile", "comments", path)
        self.assertGreater(result["words"], 0)
        self.assertFalse(result["passed"])


class FragmentTests(Harness):
    """Sentence-level rules need a sentence to apply to.

    A semicolon rule says "write two sentences". In a table cell there is no room
    for two, a heading is a fragment, and an unpunctuated list item is a label
    joining items rather than clauses. 57% of semicolon findings measured across
    17 repositories sat in one of those three.
    """

    def test_semicolon_in_a_table_cell_is_not_reported(self):
        text = ("# Title\n\n| Name | Detail |\n|---|---|\n"
                "| a | Tries OAuth first; falls back to JWT |\n")
        path = self.write("table.md", text)
        self.assertEqual(self.checks(path).get("semicolon", 0), 0)

    def test_semicolon_in_a_label_list_item_is_not_reported(self):
        text = "# Title\n\n- **Read-only:** kubectl get/describe; helm list/status\n"
        path = self.write("label.md", text)
        self.assertEqual(self.checks(path).get("semicolon", 0), 0)

    def test_semicolon_in_a_punctuated_list_item_is_still_reported(self):
        """A list item written as prose is prose, and the edit is available."""
        text = "# Title\n\n- The parser reads the file; the writer stores it.\n"
        path = self.write("proselist.md", text)
        self.assertEqual(self.checks(path).get("semicolon", 0), 1)

    def test_semicolon_joining_clauses_in_prose_is_still_reported(self):
        text = "# Title\n\nThe parser reads the file; the writer stores the record.\n"
        path = self.write("clauses.md", text)
        self.assertEqual(self.checks(path).get("semicolon", 0), 1)

    def test_tldr_is_one_token_not_two_clauses(self):
        path = self.write("tldr.md", "# Title\n\nTL;DR the parser reads the file.\n")
        self.assertEqual(self.checks(path).get("semicolon", 0), 0)


class ParticipleTests(Harness):
    """A participle can report a state instead of an action."""

    def test_stative_participles_are_not_progressive_verbs(self):
        text = ("# Title\n\nVerify the server is running. No other process is\n"
                "using port 8000. The header is missing.\n")
        path = self.write("state.md", text)
        self.assertEqual(self.checks(path).get("ing_main_verb", 0), 0)

    def test_a_real_progressive_is_still_reported(self):
        path = self.write("prog.md", "# Title\n\nThe team is introducing a new field.\n")
        self.assertEqual(self.checks(path).get("ing_main_verb", 0), 1)

    def test_one_passive_is_charged_once(self):
        """"is being drained" is one defect, not two."""
        path = self.write("dbl.md", "# Title\n\nThe queue is being drained by the worker.\n")
        counts = self.checks(path)
        self.assertEqual(counts.get("passive_voice", 0), 1)
        self.assertEqual(counts.get("ing_main_verb", 0), 0)

    def test_predicate_adjectives_are_not_passives(self):
        text = ("# Title\n\nThe flag is needed. The file is unused. The pattern is\n"
                "unchanged. The token is expired. The route is unauthenticated.\n")
        path = self.write("adj.md", text)
        self.assertEqual(self.checks(path).get("passive_voice", 0), 0)

    def test_a_real_passive_is_still_reported(self):
        path = self.write("pass.md", "# Title\n\nThe record is written by the worker.\n")
        self.assertEqual(self.checks(path).get("passive_voice", 0), 1)


class NominalizationTests(Harness):
    """A noun ending in -tion is not automatically a buried verb."""

    def test_ordinary_noun_phrases_are_not_nominalizations(self):
        text = ("# Title\n\nThe location of the bucket, the description of the\n"
                "field, and the combination of the two.\n")
        path = self.write("nouns.md", text)
        self.assertEqual(self.checks(path).get("nominalization", 0), 0)

    def test_buried_verbs_are_still_reported(self):
        text = "# Title\n\nIt simplifies the detection of drift after the deprecation of v1.\n"
        path = self.write("buried.md", text)
        self.assertEqual(self.checks(path).get("nominalization", 0), 2)

    def test_perform_needs_a_nominalized_object(self):
        path = self.write("bare.md", "# Title\n\nClients that perform PKCE directly.\n")
        self.assertEqual(self.checks(path).get("nominalization", 0), 0)
        path = self.write("obj.md", "# Title\n\nIt performs an analysis of each record.\n")
        self.assertEqual(self.checks(path).get("nominalization", 0), 1)


class LineAttributionTests(Harness):
    """A finding names the line holding the text it quotes."""

    def test_findings_in_a_wrapped_paragraph_report_their_own_lines(self):
        text = ("# Title\n\nThe parser reads the file.\n"
                "But we utilize the robust\napproach in order to facilitate this.\n")
        path = self.write("attr.md", text)
        self.assertEqual(self.lines_for("banned_word", path), [4, 5, 5])
        self.assertEqual(self.lines_for("marketing_adjective", path), [4])

    def test_findings_in_a_comment_run_report_their_own_lines(self):
        text = "const a = 1;\n// We utilize this\n// and we leverage that.\n"
        path = self.write("mod.js", text)
        self.assertEqual(
            self.lines_for("banned_word", "--profile", "comments", path), [2, 3])

    def test_paragraph_level_findings_stay_on_the_first_line(self):
        """A paragraph rule is a fact about the block, not about one offset."""
        body = " ".join("The parser reads record %d." % n for n in range(8))
        path = self.write("para.md", "# Title\n\n%s\n" % body)
        self.assertEqual(self.lines_for("long_paragraph", path), [3])


class PerformanceTests(Harness):
    """A guard, not a benchmark.

    The excerpt of a finding was built from the whole unit, once per finding, so a
    paragraph producing a finding every few words cost O(n^2). A 137KB single
    paragraph took 3.4 seconds. The bound below is loose enough for a slow machine
    and still fails if that behaviour returns.
    """

    def test_a_large_single_paragraph_stays_fast(self):
        text = "The system is designed to utilize the robust approach. " * 2500
        path = self.write("big.md", text)
        started = time.time()
        self.run_lint("--quiet", path)
        elapsed = time.time() - started
        self.assertLess(elapsed, 2.0,
                        "a %dKB paragraph took %.1fs; the excerpt cost is quadratic "
                        "again" % (len(text) // 1024, elapsed))

    def test_excerpt_is_bounded_and_still_readable(self):
        long_text = "word " * 10000
        trimmed = prose_lint.excerpt(long_text)
        # width - 1 characters plus the ellipsis that marks the truncation.
        self.assertLessEqual(len(trimmed), 70)
        self.assertTrue(trimmed.endswith("..."))
        self.assertEqual(prose_lint.excerpt("a  b   c"), "a b c")


class HostileInputTests(Harness):
    """Input the linter did not ask for, and must survive anyway."""

    def test_empty_and_whitespace_only_files_are_clean(self):
        for name, text in (("empty.md", ""), ("blank.md", "\n\n   \n")):
            path = self.write(name, text)
            code, _, _ = self.run_lint(path)
            self.assertEqual(code, 0, "%s should be clean" % name)

    def test_carriage_returns_do_not_shift_line_numbers(self):
        text = "# Title\r\n\r\nWe utilize the approach.\r\n"
        path = self.write("crlf.md", text)
        self.assertEqual(self.lines_for("banned_word", path), [3])

    def test_frontmatter_only_file_is_clean(self):
        path = self.write("fm.md", "---\ntitle: We utilize this\n---\n")
        self.assertEqual(self.run_lint(path)[0], 0)

    def test_unterminated_docstring_is_read_to_the_end(self):
        path = self.write("mod.py", '"""We utilize the seamless approach.\n')
        code, _, _ = self.run_lint("--profile", "comments", path)
        self.assertIn(code, (0, 1))

    def test_invalid_utf8_is_replaced_rather_than_raised(self):
        path = self.write_bytes("latin1.md", b"# Title\n\nCaf\xe9 utilize this.\n")
        code, _, err = self.run_lint(path)
        self.assertIn(code, (0, 1), "should not crash: %s" % err)
        self.assertNotIn("Traceback", err)

    def test_a_single_enormous_line_terminates(self):
        path = self.write("one.md", "word " * 200000)
        started = time.time()
        self.run_lint("--quiet", path)
        self.assertLess(time.time() - started, 10.0)


class GoldenTests(Harness):
    """One document, pinned whole.

    A per-check breakdown is what turns a rule edit into a reviewable diff. If
    this test fails, read the change: either a rule moved on purpose, and these
    numbers should be updated in the same commit, or it moved by accident.
    """

    DOCUMENT = """---
title: Widget Service
---

# Widget Service

The widget service is designed to utilize a seamless approach; it was built to
facilitate the processing of records. It is important to note that the queue is
being drained by the worker.

## Setup

1. Start the server.
2. The configuration is loaded by the server.

> We leverage a myriad of robust techniques.

```bash
utilize --seamless
```

Overall, the service performs an analysis of each record. It doesn't retry.
"""

    # "is being drained" scores passive_voice once, for "being drained". It used
    # to also score ing_main_verb for "is being", charging one passive twice.
    #
    # "the processing of records" scores nothing: `processing` does not end in a
    # nominalising suffix. "performs an analysis of" scores once, because that
    # one really does bury a verb.
    EXPECTED = {
        "banned_word": 4,
        "contraction": 1,
        "empty_closer": 1,
        "hedge": 1,
        "marketing_adjective": 2,
        "nominalization": 1,
        "passive_voice": 4,
        "semicolon": 1,
    }
    EXPECTED_WORDS = 65

    def test_pinned_document(self):
        path = self.write("golden.md", self.DOCUMENT)
        result = self.evaluate(path)
        self.assertEqual(result["counts"], self.EXPECTED)
        self.assertEqual(result["words"], self.EXPECTED_WORDS)
        self.assertFalse(result["passed"])

    def test_pinned_document_word_count_excludes_structure(self):
        """Frontmatter, the fenced block and the heading markers are not words."""
        path = self.write("golden.md", self.DOCUMENT)
        self.assertLess(self.evaluate(path)["words"],
                        len(self.DOCUMENT.split()),
                        "structure is being counted as prose")

    def test_pinned_document_is_clean_when_every_check_is_off(self):
        path = self.write("golden.md", self.DOCUMENT)
        args = []
        for name in prose_lint.ALL_CHECKS:
            args += ["--disable", name]
        result = self.evaluate(*(args + [path]))
        self.assertEqual(result["counts"], {})
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
