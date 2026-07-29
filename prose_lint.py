#!/usr/bin/env python3
r"""Pre-commit hook to lint prose in documentation and in source-code comments.

Language agnostic. Documentation files are linted whole. Source files are
scanned for comments and docstrings, and only that prose is linted, so code,
identifiers and string literals are never scored.

The rules are the machine-checkable subset of ASD-STE100 Simplified Technical
English: word choice, sentence length, voice, hedging, marketing language and
paragraph size. Judgment rules (is the noun the right noun, is the claim true)
need a human and are not checked here.

Three independent enforcement mechanisms:
  threshold       - weighted violations per 100 words, at or above min_words
  short_allowance - absolute violation count below min_words, where a rate says
                    more about length than about quality
  max             - absolute count cap per check, for zero-tolerance checks

Every check can be enabled, disabled or re-weighted, so a project can tune the
rule set without editing this file. Configuration comes from a profile, then a
JSON config, then command-line flags, each overriding the last.

Run --list-checks for the check names and their default weights. The README
documents the JSON schema and every flag, with examples.
"""

import argparse
import fnmatch
import json
import os
import re
import shlex
import sys

# --------------------------------------------------------------------------- #
# Rule data
# --------------------------------------------------------------------------- #

# phrase -> plain replacement ("" means delete the phrase)
BANNED = {
    "utilize": "use", "utilizes": "use", "utilized": "used", "utilizing": "using",
    "utilization": "use",
    "leverage": "use", "leverages": "uses", "leveraged": "used", "leveraging": "using",
    "facilitate": "help", "facilitates": "helps", "facilitated": "helped",
    "ensure": "make sure", "ensures": "makes sure", "ensuring": "making sure",
    "commence": "start", "commences": "starts", "commenced": "started",
    "initiate": "start", "initiates": "starts", "initiated": "started",
    "begin": "start", "begins": "starts", "began": "started",
    "terminate": "stop", "terminates": "stops", "terminated": "stopped",
    "obtain": "get", "obtains": "gets", "obtained": "got",
    "acquire": "get", "acquires": "gets", "acquired": "got",
    "demonstrate": "show", "demonstrates": "shows", "demonstrated": "showed",
    "endeavor": "try", "endeavour": "try",
    "methodology": "method", "aforementioned": "this",
    "approximately": "about", "regarding": "about", "concerning": "about",
    "whilst": "while", "amongst": "among",
    "numerous": "many", "myriad": "many", "plethora": "many",
    "additionally": "also", "furthermore": "also", "moreover": "also",
    "henceforth": "", "therein": "", "thereof": "", "herein": "",
    "in order to": "to",
    "in the event that": "if",
    "due to the fact that": "because",
    "for the purpose of": "to",
    "at this point in time": "now",
    "at the present time": "now",
    "a variety of": "several",
    "a number of": "several",
    "the fact that": "that",
    "is able to": "can", "are able to": "can",
    "has the ability to": "can", "have the ability to": "can",
    "in terms of": "for",
    "with respect to": "about",
    "with regard to": "about",
    "on a regular basis": "regularly",
    "prior to": "before",
    "subsequent to": "after",
    "serves as": "is", "acts as": "is",
}

MARKETING = [
    "seamless", "seamlessly", "robust", "powerful", "cutting-edge", "effortless",
    "effortlessly", "world-class", "next-generation", "revolutionary", "blazing",
    "lightning-fast", "elegant", "delightful", "turnkey", "best-in-class",
    "state-of-the-art", "game-changing", "first-class", "battle-tested",
    "enterprise-grade", "supercharge", "unlock", "unleash", "empower", "empowers",
    "rich set of", "sensible defaults", "minimal friction", "out of the box",
]

PHRASAL = {
    "spin up": "start", "spin down": "stop", "spun up": "started",
    "reach out": "ask", "reaching out": "asking",
    "dive into": "examine", "dives into": "examines", "diving into": "examining",
    "delve into": "examine", "deep dive": "review",
    "kick off": "start", "kicks off": "starts", "kicked off": "started",
    "roll out": "deploy", "rolls out": "deploys", "rolled out": "deployed",
    "tear down": "remove", "ramp up": "increase",
    "circle back": "revisit", "drill down": "examine",
    "stand up": "create", "stood up": "created",
}

HEDGE = [
    "it is important to note", "it should be noted", "it is worth noting",
    "please note that", "as mentioned", "as noted above", "as we all know",
    "needless to say", "it goes without saying", "arguably", "generally speaking",
]

INTENSIFIER = [
    "very", "really", "quite", "extremely", "incredibly", "dramatically",
    "significantly", "substantially", "highly", "vastly", "immensely",
]

CLOSER = [
    "in summary", "in conclusion", "to summarize", "overall,", "all in all",
    "at the end of the day", "provides a foundation", "provides a solid foundation",
    "sets the stage", "paves the way", "going forward", "in today's",
    "the possibilities are endless",
]

# Participles that read as adjectives, not as a passive with a hidden actor.
# Kept identical to the skill's list on purpose. "is deprecated", "is documented"
# and "is supported" were exempt here and are not exempt in the skill: each has a
# hidden actor worth naming, so the skill's stricter reading wins.
PASSIVE_OK = {
    "based", "related", "unrelated", "required", "intended", "supposed",
    "limited", "interested", "aware", "expected", "involved", "located",
}

BE = r"(?:am|is|are|was|were|be|been|being)"

# Nouns and prepositions that end in -ing. "The result is something" is not a
# progressive verb, so the ing_main_verb check has to skip these.
ING_NOUN = {
    "anything", "something", "nothing", "everything", "thing", "things",
    "during", "morning", "evening", "spring", "string", "strings", "king",
    "ring", "ceiling", "sibling", "siblings", "offering", "offerings",
    "warning", "warnings", "meaning", "engineering", "onboarding", "tooling",
    "logging", "monitoring", "backing", "wiring", "casing", "sampling",
}

# Contractions of "to be" or "to have" that end in 's. The possessive check has
# to let these through, otherwise the most common contraction of all is invisible.
S_CONTRACTIONS = {
    "it's", "that's", "there's", "let's", "what's", "here's", "he's", "she's",
    "who's", "where's", "how's", "one's", "everything's", "nothing's",
}

PP_IRREG = (
    r"(?:done|made|sent|read|built|kept|held|set|put|run|written|shown|given"
    r"|taken|found|got|gotten|seen|known|thrown|drawn|left|lost|meant|sold)"
)
NOMINALIZATION = re.compile(
    r"\b(?:perform(?:s|ed)?|conduct(?:s|ed)?|carry out|carries out"
    r"|make use of|makes use of|take (?:a look|action))\b",
    re.I,
)
NOMINAL_OF = re.compile(r"\b(\w{4,}(?:tion|ment|ance|ence))\s+of\b", re.I)

FIX_HINT = {
    "long_sentence": "split into one idea per sentence",
    "long_paragraph": "one topic per paragraph",
    "semicolon": "replace with a period and two sentences",
    "contraction": "expand it",
    "passive_voice": "name the actor and use active voice",
    "ing_main_verb": "use a simple tense",
    "nominalization": "use the verb directly",
    "phrasal_verb": "use a single plain verb",
    "banned_word": "use the short common word",
    "marketing_adjective": "delete it or state a measured fact",
    "hedge": "delete the hedge and state the fact",
    "intensifier": "delete it or give the number",
    "empty_closer": "delete it or replace it with a fact",
}

# --------------------------------------------------------------------------- #
# Checks: name -> (default weight, default absolute cap or None)
# --------------------------------------------------------------------------- #

ALL_CHECKS = [
    "long_sentence", "long_paragraph", "semicolon", "contraction",
    "passive_voice", "ing_main_verb", "nominalization", "phrasal_verb",
    "banned_word", "marketing_adjective", "hedge", "intensifier", "empty_closer",
]

# Every check weighs 1.0, so the score is a plain violation count per 100 words
# and matches the technical-writing skill's linter on the same text. Two tools
# reporting different numbers for one document is its own problem: a reviewer
# cannot tell whether prose improved or the scorer changed its mind.
#
# The weighting machinery stays, because --weight and the JSON config are how a
# project tunes this without editing the file. Only the defaults are uniform. Set
# a weight below 1.0 to make a check advisory, above 1.0 to make one count double.
DEFAULT_WEIGHTS = dict((name, 1.0) for name in ALL_CHECKS)

# Checks that are almost always right, even on a terse code comment.
HIGH_SIGNAL = ["banned_word", "marketing_adjective", "hedge", "empty_closer"]

# Everything except intensifiers. The skill checks intensifiers in strict mode
# only, because "significantly" and "highly" carry real meaning in a design doc
# and the relaxed word list is what lets standard prose keep its range.
DOC_CHECKS = [name for name in ALL_CHECKS if name != "intensifier"]

# --------------------------------------------------------------------------- #
# Why `short_allowance` exists, and why it is 1
#
# The document profiles mirror the technical-writing skill's linter, which is the
# source of truth for these numbers: a 100-word floor, allowance 1 at the standard
# threshold and 0 in strict mode, and a count rather than a rate below the floor.
#
# The rate is violations / words * 100 against a threshold of 2.0, so prose gets
# 50 words of runway per allowed violation. Below roughly 100 words that rate is a
# near-binary the threshold slices through arbitrarily. Measured on a 43-file,
# 17k-word corpus, with the rate alone:
#
#     words  violations  score  verdict
#        36           1   2.78  FAIL
#        45           1   2.22  FAIL
#        52           1   1.92  PASS
#        50           2   4.00  FAIL
#
# Identical defect counts, opposite verdicts, seven words apart. Of 13 documents
# under 100 words, 10 carried zero violations, so short prose can reach zero and
# the rate was not doing useful work at that length.
#
# The rate also does not compare across lengths. A score of 2.78 is one defect in
# 36 words and about 55 defects in 2000. Ranking by score put a 50-word index page
# at 4.00 above a 1937-word architecture document at 3.56, so the metric
# misdirected an audit rather than guiding it.
#
# Allowance of 1 was chosen over the alternatives. Zero is stricter than the old
# behavior, flips the 52-word file from pass to fail, and lets a single "don't"
# gate a commit. Two means nothing under 100 words could realistically fail, so
# the check stops catching anything. One removes the cliff, still fails prose with
# two real defects, and states in one sentence with no arithmetic: short prose may
# carry at most one violation. The `strict` profile takes 0 deliberately, because
# error messages and commit bodies are short by nature and have no budget
# argument.
#
# REJECTED, deliberately: a denominator floor, per_100w = violations * 100 /
# max(words, 100). It is one line and yields similar verdicts, but it reports a
# rate that was never measured -- a reader seeing 1.0 on a 23-word document would
# infer 0.23 violations. The rule here changes the verdict and keeps the reported
# number true, which is why short prose prints a count and no rate at all.
# Collapsing `is_short` and `short_allowance` back into a denominator fudge is a
# regression, not a simplification.
# --------------------------------------------------------------------------- #

PROFILES = {
    # Whole-file documentation. Every check, rate-based enforcement.
    "docs": {
        "enabled": list(DOC_CHECKS),
        "threshold": 2.0,
        "min_words": 100,
        "short_allowance": 1,
        "max_sentence_words": 25,
        "max_paragraph_sentences": 6,
        "max": {},
    },
    # Procedures, runbooks, error text. Tighter caps, no hedging allowed.
    "strict": {
        "enabled": list(ALL_CHECKS),
        "threshold": 0.5,
        "min_words": 100,
        "short_allowance": 0,
        "max_sentence_words": 20,
        "max_paragraph_sentences": 6,
        "max": {"hedge": 0, "marketing_adjective": 0},
    },
    # Source-code comments. Comments are terse fragments, so sentence, paragraph
    # and voice rules do not apply.
    #
    # Marketing words, hedges and empty closers carry an absolute cap: one of
    # them in a comment is worth flagging however short the comment is. The
    # banned-word list stays rate-based, because it spans everything from clear
    # slop ("utilize") to words that read as ordinary English in a docstring
    # ("ensure"). An absolute cap there fails normal code on its first commit,
    # which is how a hook gets switched off.
    #
    # This profile deliberately does not follow the skill. The skill governs whole
    # documents, and its 100-word floor is calibrated for one. Comment prose is a
    # different unit: a 40-word floor keeps the rate meaningful for a file with a
    # handful of docstrings, where a 100-word floor would switch the rate off for
    # most files and leave only the caps.
    #
    # `short_allowance` is null here on purpose. A count rule on a short comment
    # would put banned_word back under an absolute cap by the back door, which is
    # the outcome the rate-based split above exists to avoid. The zero caps
    # already give the high-signal checks zero tolerance at any length.
    "comments": {
        "enabled": list(HIGH_SIGNAL),
        "threshold": 2.0,
        "min_words": 40,
        "short_allowance": None,
        "max_sentence_words": 30,
        "max_paragraph_sentences": 0,
        "max": {"marketing_adjective": 0, "hedge": 0, "empty_closer": 0},
    },
}

# --------------------------------------------------------------------------- #
# Language table for comment extraction
# --------------------------------------------------------------------------- #


class Syntax(object):
    """Comment and string delimiters for one language family.

    `docs` are extracted as prose. `strings` are skipped so that a quoted "//"
    or "#" is never mistaken for a comment.
    """

    def __init__(self, lines=(), blocks=(), strings=('"', "'"), docs=()):
        self.lines = list(lines)
        self.blocks = list(blocks)
        self.strings = list(strings)
        self.docs = list(docs)


HASH = Syntax(lines=["#"])
SLASH = Syntax(lines=["//"], blocks=[("/*", "*/")])
DASH = Syntax(lines=["--"], blocks=[("--[[", "]]")])
SEMI = Syntax(lines=[";"])
MARKUP = Syntax(blocks=[("<!--", "-->")], strings=['"', "'"])
PYTHON = Syntax(lines=["#"], docs=['"""', "'''"])

LANGUAGES = {
    # hash comments
    ".py": PYTHON, ".pyi": PYTHON,
    ".sh": HASH, ".bash": HASH, ".zsh": HASH, ".fish": HASH,
    ".rb": Syntax(lines=["#"], blocks=[("=begin", "=end")]),
    ".pl": HASH, ".pm": HASH, ".r": HASH, ".jl": HASH, ".nim": HASH,
    ".yaml": HASH, ".yml": HASH, ".toml": HASH, ".cfg": HASH, ".conf": HASH,
    ".tf": Syntax(lines=["#", "//"], blocks=[("/*", "*/")]),
    ".tfvars": HASH, ".dockerfile": HASH, ".mk": HASH, ".gitignore": HASH,
    ".ex": HASH, ".exs": HASH, ".cr": HASH, ".coffee": HASH,
    # slash comments
    ".c": SLASH, ".h": SLASH, ".cpp": SLASH, ".cc": SLASH, ".hpp": SLASH,
    ".cs": SLASH, ".java": SLASH, ".kt": SLASH, ".kts": SLASH, ".scala": SLASH,
    ".js": SLASH, ".jsx": SLASH, ".mjs": SLASH, ".cjs": SLASH,
    ".ts": SLASH, ".tsx": SLASH, ".go": SLASH, ".rs": SLASH, ".swift": SLASH,
    ".php": Syntax(lines=["//", "#"], blocks=[("/*", "*/")]),
    ".dart": SLASH, ".proto": SLASH, ".groovy": SLASH, ".gradle": SLASH,
    ".css": Syntax(blocks=[("/*", "*/")]), ".scss": SLASH, ".less": SLASH,
    ".m": SLASH, ".mm": SLASH, ".zig": SLASH, ".v": SLASH,
    # dash comments
    ".sql": Syntax(lines=["--"], blocks=[("/*", "*/")]),
    ".lua": DASH, ".hs": Syntax(lines=["--"], blocks=[("{-", "-}")]),
    ".elm": DASH, ".ada": Syntax(lines=["--"]), ".vhd": Syntax(lines=["--"]),
    # semicolon comments
    ".lisp": SEMI, ".el": SEMI, ".clj": SEMI, ".cljs": SEMI, ".scm": SEMI,
    ".ini": Syntax(lines=[";", "#"]), ".asm": SEMI, ".s": SEMI,
    # markup
    ".html": MARKUP, ".htm": MARKUP, ".xml": MARKUP, ".svg": MARKUP,
    ".vue": MARKUP, ".xhtml": MARKUP,
    # other
    ".erl": Syntax(lines=["%"]), ".tex": Syntax(lines=["%"]),
    ".ps1": Syntax(lines=["#"], blocks=[("<#", "#>")]),
    ".bat": Syntax(lines=["REM ", "::"]), ".vim": Syntax(lines=['"']),
}

DOC_EXTENSIONS = {".md", ".markdown", ".mdx", ".rst", ".txt", ".adoc", ".org"}

# Filenames without a useful extension.
BY_NAME = {
    "Dockerfile": HASH, "Makefile": HASH, "Rakefile": HASH, "Gemfile": HASH,
    "Jenkinsfile": SLASH, "Vagrantfile": HASH, "Brewfile": HASH,
    "README": None, "LICENSE": None,
}

# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


class Segment(object):
    """One run of prose with the source line its first character sits on."""

    def __init__(self, line, text, kind="prose"):
        self.line = line
        self.text = text
        self.kind = kind


def _skip_string(text, i, line, quote):
    """Advance past a string literal, honouring backslash escapes."""
    n = len(text)
    i += len(quote)
    while i < n:
        if text[i] == "\\":
            if text[i:i + 2] == "\\\n":
                line += 1
            i += 2
            continue
        if text.startswith(quote, i):
            return i + len(quote), line
        if text[i] == "\n":
            line += 1
            # An unterminated single-char quote is far more likely an apostrophe
            # than a string, so stop at the newline rather than eating the file.
            if len(quote) == 1:
                return i + 1, line
        i += 1
    return n, line


def extract_comments(text, syntax):
    """Return comment segments from source code, in file order."""
    out = []
    i, line, n = 0, 1, len(text)

    # A shebang is machine configuration, not prose.
    if text.startswith("#!"):
        i = text.find("\n")
        if i == -1:
            return out
        i += 1
        line = 2

    while i < n:
        if text[i] == "\n":
            line += 1
            i += 1
            continue

        matched = False

        # Docstrings first: in Python a triple-quoted string is documentation.
        for token in syntax.docs:
            if text.startswith(token, i):
                end = text.find(token, i + len(token))
                if end == -1:
                    end = n
                body = text[i + len(token):end]
                out.append(Segment(line, body, "block"))
                line += text.count("\n", i, min(end + len(token), n))
                i = min(end + len(token), n)
                matched = True
                break
        if matched:
            continue

        for quote in syntax.strings:
            if text.startswith(quote, i):
                i, line = _skip_string(text, i, line, quote)
                matched = True
                break
        if matched:
            continue

        for open_token, close_token in syntax.blocks:
            if text.startswith(open_token, i):
                end = text.find(close_token, i + len(open_token))
                if end == -1:
                    end = n
                body = text[i + len(open_token):end]
                out.append(Segment(line, body, "block"))
                line += text.count("\n", i, min(end + len(close_token), n))
                i = min(end + len(close_token), n)
                matched = True
                break
        if matched:
            continue

        for token in syntax.lines:
            if text.startswith(token, i):
                end = text.find("\n", i)
                if end == -1:
                    end = n
                out.append(Segment(line, text[i + len(token):end], "line"))
                i = end
                matched = True
                break
        if matched:
            continue

        i += 1
    return out


BLOCK_ORNAMENT = re.compile(r"^\s*[*!/#=\-]+\s?")
DIRECTIVE = re.compile(
    r"^\s*(?:@\w+|:\w+:|\w+:\/\/|(?:type|param|returns?|raises?|yields?|arg|args|"
    r"attribute|attributes|note|todo|fixme|noqa|pylint|eslint|prettier|ruff|mypy|"
    r"pragma|see|since|deprecated|example|examples|usage)\b[\s:])",
    re.I,
)


def group_line_comments(segments):
    """Group runs of contiguous single-line comments.

    Returns a list of (kind, parts), where parts is a list of (line, text). A
    sentence is often wrapped across several consecutive comment lines, so the
    run has to be rejoined before sentence checks can see it. Parts keep their
    own line numbers so that findings and ignore markers stay line-accurate.
    """
    groups = []
    current = None
    last_line = None
    for seg in segments:
        if seg.kind == "block":
            if current:
                groups.append(("line", current))
                current, last_line = None, None
            parts = [(seg.line + offset, part)
                     for offset, part in enumerate(seg.text.split("\n"))]
            groups.append(("block", parts))
            continue
        if current is not None and last_line is not None and seg.line == last_line + 1:
            current.append((seg.line, seg.text))
        else:
            if current:
                groups.append(("line", current))
            current = [(seg.line, seg.text)]
        last_line = seg.line
    if current:
        groups.append(("line", current))
    return groups


# markdown handling
FENCE = re.compile(r"^\s{0,3}(?:```|~~~)")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
HRULE = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
RST_DIRECTIVE = re.compile(r"^\s*\.\.\s")
IGNORE_LINE = re.compile(r"(?:<!--|#|//)\s*prose-lint:\s*ignore\s*(?:-->)?")
IGNORE_START = re.compile(r"(?:<!--|#|//)\s*prose-lint:\s*ignore-start\s*(?:-->)?")
IGNORE_END = re.compile(r"(?:<!--|#|//)\s*prose-lint:\s*ignore-end\s*(?:-->)?")


def mask_inline(text):
    """Remove spans that are code or addresses, not prose."""
    text = re.sub(r"``[^`]*``|`[^`]*`", " CODE ", text)
    text = re.sub(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,9}|#\d{1,5}|#x[0-9a-fA-F]{1,5});",
                  " ", text)                            # &nbsp; is not a semicolon
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " IMAGE ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"<https?://[^>]*>|https?://\S+", " URL ", text)
    text = re.sub(r"<!--.*?-->", " ", text)
    text = re.sub(r"<[^>]{1,40}>", " ", text)
    return text


def structural_lines(src):
    """Line numbers that are frontmatter or fenced code, and lines the ignore
    markers suppress.

    Fence and frontmatter state must resolve before anything else can skip a
    line, otherwise a skipped fence marker inverts the fence state and swallows
    the rest of the file.
    """
    structural = set()
    in_fence = False
    in_frontmatter = src[:1] == ["---"]
    for i, text in enumerate(src, start=1):
        if in_frontmatter:
            structural.add(i)
            if i > 1 and text.strip() in ("---", "..."):
                in_frontmatter = False
            continue
        if FENCE.match(text):
            in_fence = not in_fence
            structural.add(i)
            continue
        if in_fence:
            structural.add(i)

    ignored = set()
    block, marked, in_region = [], False, False
    for i, text in enumerate(src, start=1):
        if i in structural:
            continue
        if IGNORE_START.search(text):
            in_region = True
        if in_region:
            ignored.add(i)
            if IGNORE_END.search(text):
                in_region = False
            continue
        if text.strip():
            block.append(i)
            marked = marked or bool(IGNORE_LINE.search(text))
        else:
            if marked:
                ignored.update(block)
            block, marked = [], False
    if marked:
        ignored.update(block)
    return structural, ignored


def extract_document(text):
    """Return paragraph blocks for a documentation file.

    Each block is a list of units. A unit is one logical sentence run, rejoined
    from however many source lines it was hard-wrapped across.
    """
    src = text.split("\n")
    structural, ignored = structural_lines(src)
    blocks, block = [], []

    for i, raw in enumerate(src, start=1):
        skip = (
            i in structural
            or i in ignored
            or HRULE.match(raw)
            or RST_DIRECTIVE.match(raw)
            or (raw.strip() and raw.startswith("    ") and not LIST_ITEM.match(raw))
        )
        masked = mask_inline(raw)
        if skip or not masked.strip():
            if block:
                blocks.append(block)
                block = []
            continue

        if HEADING.match(raw):
            if block:
                blocks.append(block)
                block = []
            heading = HEADING.match(masked)
            blocks.append([Segment(i, heading.group(2) if heading else masked, "heading")])
            continue
        if TABLE_ROW.match(raw):
            if block:
                blocks.append(block)
                block = []
            blocks.append([Segment(i, masked.replace("|", " "), "table")])
            continue

        if LIST_ITEM.match(raw):
            block.append(Segment(i, LIST_ITEM.sub("", masked), "list"))
        elif raw.lstrip().startswith(">"):
            block.append(Segment(i, masked.lstrip().lstrip(">").strip(), "quote"))
        elif block and block[-1].kind in ("list", "quote"):
            block[-1].text += " " + masked.strip()
        elif block and block[-1].kind == "prose":
            block[-1].text += " " + masked.strip()
        else:
            block.append(Segment(i, masked.strip(), "prose"))

    if block:
        blocks.append(block)
    return blocks


def extract_comment_blocks(text, syntax):
    """Return paragraph blocks for a source file, from its comments only."""
    raw_segments = extract_comments(text, syntax)
    src = text.split("\n")
    _, ignored = structural_lines(src)
    units = []
    for kind, parts in group_line_comments(raw_segments):
        # Parts keep their own line numbers, so an ignore marker anywhere inside
        # a multi-line comment suppresses only the lines it covers.
        if kind == "block":
            parts = [(line, BLOCK_ORNAMENT.sub("", part).strip())
                     for line, part in parts]
        else:
            parts = [(line, part.strip()) for line, part in parts]
        parts = [(line, part) for line, part in parts
                 if part and line not in ignored and not DIRECTIVE.match(part)]
        if not parts:
            continue
        joined = mask_inline(" ".join(part for _, part in parts)).strip()
        if joined:
            units.append(Segment(parts[0][0], joined, "comment"))
    return [[unit] for unit in units]

# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #

# Do not split after an abbreviation. Each lookbehind must be fixed width, so
# they are listed separately rather than as one alternation. The lone-capital
# rule needs the leading space: without it, a sentence ending in an acronym
# ("... aligned with MRC.") would never split.
_NOT_ABBREV = (
    r"(?<![Ee]\.[Gg]\.)(?<![Ii]\.[Ee]\.)(?<!\bvs\.)(?<!\betc\.)(?<!\bcf\.)"
    r"(?<!\bal\.)(?<!\bInc\.)(?<!\bLtd\.)(?<!\bNo\.)(?<!\bFig\.)"
    r"(?<!\bapprox\.)(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\s[A-Z]\.)"
)
# A sentence may open with markdown emphasis or a link bracket. Without these in
# the lookahead, "Foo. **Bar** does X." reads as one sentence and its length is
# reported as the sum of both.
_SENT_LEAD = r"""[*_`\[]*[A-Z0-9"'(]"""
SENT_SPLIT = re.compile(r"(?<=[.!?])" + _NOT_ABBREV + r"\s+(?=" + _SENT_LEAD + r")")
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-/]*")


def sentences(text):
    return [p.strip() for p in SENT_SPLIT.split(text) if p.strip()]


def word_count(text):
    return len(WORD.findall(text))


def excerpt(text, width=68):
    # Slice before normalising. Only the first `width` characters can survive the
    # truncation below, so collapsing whitespace across the whole text is wasted
    # work -- and it is charged once per finding, which makes a paragraph that
    # yields a finding every few words cost O(n^2). A 137KB single paragraph took
    # 3.4s before this slice and 0.02s after.
    text = " ".join(text[:width * 8].split())
    return text if len(text) <= width else text[:width - 1] + "..."


def find_phrases(text, phrases):
    """Return (phrase, suggestion) for each occurrence, case-insensitively."""
    hits = []
    low = text.lower()
    items = phrases.items() if isinstance(phrases, dict) else [(p, None) for p in phrases]
    for phrase, suggestion in items:
        pattern = r"(?<![a-z])" + re.escape(phrase.lower()) + r"(?![a-z])"
        for _ in re.finditer(pattern, low):
            hits.append((phrase, suggestion))
    return hits


class Finding(object):
    def __init__(self, line, check, detail, excerpt_text=""):
        self.line = line
        self.check = check
        self.detail = detail
        self.excerpt = excerpt_text


def run_checks(blocks, cfg):
    """Apply every enabled check. Returns a list of Findings."""
    out = []
    enabled = cfg["enabled"]
    banned = cfg["banned"]
    marketing = cfg["marketing"]

    def add(line, check, detail, text=""):
        if check in enabled:
            out.append(Finding(line, check, detail, excerpt(text)))

    for block in blocks:
        sentence_total = 0
        for unit in block:
            text = unit.text
            line = unit.line

            # Sentence length: skip headings and table cells, which are fragments.
            if unit.kind not in ("heading", "table"):
                for sentence in sentences(text):
                    sentence_total += 1
                    length = word_count(sentence)
                    if length > cfg["max_sentence_words"]:
                        add(line, "long_sentence",
                            "%d words (max %d)" % (length, cfg["max_sentence_words"]),
                            sentence)

            for _ in re.finditer(r";", text):
                add(line, "semicolon", "semicolon", text)

            for match in re.finditer(r"\b\w+['’](?:t|re|ve|ll|d|s|m)\b", text):
                word = match.group(0)
                norm = word.lower().replace("’", "'")
                if norm.endswith("'s") and norm not in S_CONTRACTIONS:
                    continue                    # possessive, not a contraction
                add(line, "contraction", word, text)

            for match in re.finditer(r"\b(%s)\s+(\w+ed|%s)\b" % (BE, PP_IRREG), text, re.I):
                if match.group(2).lower() in PASSIVE_OK:
                    continue
                add(line, "passive_voice", match.group(0), text)

            for match in re.finditer(r"\b%s\s+(\w+ing)\b" % BE, text, re.I):
                if match.group(1).lower() in ING_NOUN:
                    continue                            # a noun, not a verb
                add(line, "ing_main_verb", match.group(0), text)

            for match in NOMINALIZATION.finditer(text):
                add(line, "nominalization", match.group(0), text)
            for match in NOMINAL_OF.finditer(text):
                add(line, "nominalization", "%s of" % match.group(1), text)

            for phrase, suggestion in find_phrases(text, PHRASAL):
                add(line, "phrasal_verb", '"%s" -> %s' % (phrase, suggestion), text)

            for phrase, suggestion in find_phrases(text, banned):
                fix = "-> %s" % suggestion if suggestion else "-> delete"
                add(line, "banned_word", '"%s" %s' % (phrase, fix), text)

            for phrase, _ in find_phrases(text, marketing):
                add(line, "marketing_adjective", '"%s"' % phrase, text)

            for phrase, _ in find_phrases(text, HEDGE):
                add(line, "hedge", '"%s"' % phrase, text)

            for phrase, _ in find_phrases(text, INTENSIFIER):
                add(line, "intensifier", '"%s"' % phrase, text)

            for phrase, _ in find_phrases(text, CLOSER):
                add(line, "empty_closer", '"%s"' % phrase, text)

        cap = cfg["max_paragraph_sentences"]
        if cap and sentence_total > cap and not any(
                u.kind in ("list", "heading", "table") for u in block):
            add(block[0].line, "long_paragraph",
                "%d sentences (max %d)" % (sentence_total, cap), block[0].text)

    out.sort(key=lambda f: (f.line, f.check))
    return out

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def build_config(args):
    """Merge profile defaults, JSON config and CLI overrides, in that order."""
    raw = {}
    if args.config:
        if os.path.isfile(args.config):
            with open(args.config) as handle:
                raw = json.load(handle)
        else:
            try:
                raw = json.loads(args.config)
            except ValueError as exc:
                raise ConfigError("--config is neither a readable file "
                                 "nor valid JSON (%s)" % exc)
    if not isinstance(raw, dict):
        raise ConfigError("--config must be a JSON object")

    profile_name = args.profile or raw.get("profile") or "docs"
    if profile_name not in PROFILES:
        raise ConfigError("unknown profile %r (choose from %s)"
                         % (profile_name, ", ".join(sorted(PROFILES))))
    profile = PROFILES[profile_name]

    cfg = {
        "profile": profile_name,
        "threshold": profile["threshold"],
        "min_words": profile["min_words"],
        "short_allowance": profile["short_allowance"],
        "max_sentence_words": profile["max_sentence_words"],
        "max_paragraph_sentences": profile["max_paragraph_sentences"],
        "weights": dict(DEFAULT_WEIGHTS),
        "max": dict(profile["max"]),
        "enabled": set(profile["enabled"]),
    }

    for key in ("threshold", "min_words", "short_allowance",
                "max_sentence_words", "max_paragraph_sentences"):
        if key in raw:
            cfg[key] = raw[key]

    for name, spec in (raw.get("checks") or {}).items():
        if name not in ALL_CHECKS:
            raise ConfigError("unknown check %r in config (choose from %s)"
                             % (name, ", ".join(ALL_CHECKS)))
        if not isinstance(spec, dict):
            raise ConfigError("config for check %r must be an object" % name)
        if spec.get("enabled") is True:
            cfg["enabled"].add(name)
        elif spec.get("enabled") is False:
            cfg["enabled"].discard(name)
        if "weight" in spec:
            cfg["weights"][name] = float(spec["weight"])
        if "max" in spec:
            cfg["max"][name] = None if spec["max"] is None else int(spec["max"])

    # CLI overrides win over the JSON config.
    if args.threshold is not None:
        cfg["threshold"] = args.threshold
    if args.min_words is not None:
        cfg["min_words"] = args.min_words
    if args.short_allowance is not None:
        cfg["short_allowance"] = args.short_allowance
    if args.max_sentence_words is not None:
        cfg["max_sentence_words"] = args.max_sentence_words
    if args.max_paragraph_sentences is not None:
        cfg["max_paragraph_sentences"] = args.max_paragraph_sentences

    for name in args.enable or []:
        if name not in ALL_CHECKS:
            raise ConfigError("unknown check %r" % name)
        cfg["enabled"].add(name)
    for name in args.disable or []:
        if name not in ALL_CHECKS:
            raise ConfigError("unknown check %r" % name)
        cfg["enabled"].discard(name)
    for item in args.weight or []:
        name, _, value = item.partition("=")
        if name not in ALL_CHECKS or not value:
            raise ConfigError("--weight expects CHECK=NUMBER, got %r" % item)
        cfg["weights"][name] = float(value)
    for item in args.max or []:
        name, _, value = item.partition("=")
        if name not in ALL_CHECKS or not value:
            raise ConfigError("--max expects CHECK=INTEGER, got %r" % item)
        cfg["max"][name] = int(value)

    # Project vocabulary.
    banned = dict(BANNED)
    banned.update(raw.get("extra_banned") or {})
    marketing = list(MARKETING) + list(raw.get("extra_marketing") or [])
    allow = set(word.lower() for word in (raw.get("allow") or []))
    allow.update(word.lower() for word in (args.allow or []))
    for word in allow:
        banned.pop(word, None)
    marketing = [word for word in marketing if word.lower() not in allow]

    cfg["banned"] = banned
    cfg["marketing"] = marketing
    cfg["allow"] = allow
    return cfg

# --------------------------------------------------------------------------- #
# Scoring and reporting
# --------------------------------------------------------------------------- #


def score(findings, words, cfg):
    """Weighted violations per 100 words, plus per-check counts."""
    counts = {}
    weighted = 0.0
    for finding in findings:
        counts[finding.check] = counts.get(finding.check, 0) + 1
        weighted += cfg["weights"].get(finding.check, 1.0)
    rate = round(weighted * 100.0 / words, 2) if words else 0.0
    return counts, round(weighted, 2), rate


def evaluate(path, text, cfg, kind, syntax):
    if kind == "doc":
        blocks = extract_document(text)
    else:
        blocks = extract_comment_blocks(text, syntax)

    words = sum(word_count(unit.text) for block in blocks for unit in block)
    findings = run_checks(blocks, cfg)
    counts, weighted, rate = score(findings, words, cfg)

    # Headings and table cells are fragments, so they are excluded here for the
    # same reason the long_sentence check excludes them.
    longest = max((word_count(sentence)
                   for block in blocks for unit in block
                   if unit.kind not in ("heading", "table")
                   for sentence in sentences(unit.text)), default=0)

    reasons = []
    for name, cap in sorted(cfg["max"].items()):
        if cap is None or name not in cfg["enabled"]:
            continue
        found = counts.get(name, 0)
        if found > cap:
            reasons.append("%s: %d found, max %d" % (name, found, cap))

    # Below min_words a rate is meaningless: at threshold 2.0 prose needs 50 words
    # of runway per allowed violation, so one defect passes at 52 words and fails
    # at 45. Short prose is judged on the absolute count instead, and its rate is
    # not reported as a verdict at all. A null allowance disables the count rule
    # and leaves only the per-check caps, which is what the comments profile wants.
    short = words < cfg["min_words"]
    allowance = cfg["short_allowance"]
    found = len(findings)
    if short:
        if allowance is not None and found > allowance:
            reasons.append("%d violation%s in %d words (short-doc rule: max %d)"
                           % (found, "" if found == 1 else "s", words, allowance))
    elif rate > cfg["threshold"]:
        reasons.append("score %.2f per 100 words, max %.2f" % (rate, cfg["threshold"]))

    return {
        "path": path,
        "kind": kind,
        "words": words,
        "findings": findings,
        "counts": counts,
        "weighted": weighted,
        "rate": rate,
        "longest_sentence": longest,
        "is_short": short,
        "short_allowance": allowance,
        "reasons": reasons,
        "passed": not reasons,
    }


def totals(results):
    """Corpus rollup across every file linted in one run.

    The corpus rate is recomputed from the pooled weight and word count, not
    averaged from the per-file rates, so a long file counts for more than a
    three-line one.
    """
    words = sum(result["words"] for result in results)
    weighted = sum(result["weighted"] for result in results)
    counts = {}
    for result in results:
        for name, found in result["counts"].items():
            counts[name] = counts.get(name, 0) + found
    return {
        "files": len(results),
        "failing": sum(1 for result in results if not result["passed"]),
        "short_files": sum(1 for result in results if result["is_short"]),
        "words": words,
        "findings": sum(counts.values()),
        "weighted": round(weighted, 2),
        "rate": round(weighted * 100.0 / words, 2) if words else 0.0,
        "longest_sentence": max((result["longest_sentence"]
                                 for result in results), default=0),
        "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
    }


def print_totals(total, cfg):
    """Human-readable rollup. Goes to stderr, because stdout carries --json."""
    short = ", %d short" % total["short_files"] if total["short_files"] else ""
    err("prose-lint TOTAL  %d files, %d words, %d failing%s"
        % (total["files"], total["words"], total["failing"], short))
    err("  score %.2f per 100 words (max %.2f)  longest sentence %d words"
        % (total["rate"], cfg["threshold"], total["longest_sentence"]))
    for name, found in total["counts"].items():
        share = found * 100.0 / max(total["findings"], 1)
        err("  %-22s %5d  %5.1f%%" % (name, found, share))


def err(message):
    """Print a string to stderr."""
    print(message, file=sys.stderr)


class ConfigError(Exception):
    """Bad configuration or usage. Reported with exit code 2, not 1, so that a
    caller can tell a misconfigured hook from prose that failed the budget."""


def report(result, quiet):
    for finding in result["findings"]:
        hint = FIX_HINT.get(finding.check, "")
        err("%s:%d: %s: %s%s" % (result["path"], finding.line, finding.check,
                                 finding.detail, " (%s)" % hint if hint else ""))
        if finding.excerpt and not quiet:
            err("    %s" % finding.excerpt)
    for reason in result["reasons"]:
        err("%s: FAIL %s" % (result["path"], reason))


def classify(path, include_unknown):
    """Return (kind, syntax) for a path, or (None, None) when unsupported."""
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    if ext in DOC_EXTENSIONS:
        return "doc", None
    if ext in LANGUAGES:
        return "code", LANGUAGES[ext]
    if name in BY_NAME and BY_NAME[name] is not None:
        return "code", BY_NAME[name]
    if not ext and include_unknown:
        return "doc", None
    return None, None


def main():
    parser = argparse.ArgumentParser(
        description="Lint prose in documentation and source-code comments.")
    parser.add_argument("filenames", nargs="*")
    parser.add_argument("--profile", choices=sorted(PROFILES), default=None,
                        help="rule preset (default: docs)")
    parser.add_argument("--config", default=None,
                        help="JSON config, as an inline string or a file path")
    parser.add_argument("--threshold", type=float, default=None,
                        help="maximum weighted violations per 100 words")
    parser.add_argument("--min-words", type=int, default=None, dest="min_words",
                        help="below this word count, judge on the absolute "
                             "violation count instead of the rate")
    parser.add_argument("--short-allowance", type=int, default=None,
                        dest="short_allowance", metavar="N",
                        help="violations tolerated below --min-words "
                             "(default: 1 docs, 0 strict, none for comments)")
    parser.add_argument("--max-sentence-words", type=int, default=None,
                        dest="max_sentence_words")
    parser.add_argument("--max-paragraph-sentences", type=int, default=None,
                        dest="max_paragraph_sentences")
    parser.add_argument("--enable", action="append", metavar="CHECK")
    parser.add_argument("--disable", action="append", metavar="CHECK")
    parser.add_argument("--weight", action="append", metavar="CHECK=NUMBER")
    parser.add_argument("--max", action="append", metavar="CHECK=INTEGER")
    parser.add_argument("--allow", action="append", metavar="WORD",
                        help="drop a word from the banned and marketing lists")
    parser.add_argument("--exclude", action="append", metavar="GLOB",
                        help="skip paths matching this glob")
    parser.add_argument("--include-unknown", action="store_true",
                        help="treat extensionless files as documentation")
    parser.add_argument("--warn-only", action="store_true",
                        help="report findings as warnings and exit 0")
    parser.add_argument("--quiet", action="store_true",
                        help="omit the quoted excerpt under each finding")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="emit machine-readable results")
    parser.add_argument("--total", action="store_true",
                        help="add a corpus rollup: score, failing count, check shares")
    parser.add_argument("--list-checks", action="store_true",
                        help="print the checks with default weights and exit")

    # Allow pre-commit try-repo to pass in additional arguments
    if os.environ.get("PRE_COMMIT_TRY_ARGS"):
        sys.argv.extend(shlex.split(os.environ["PRE_COMMIT_TRY_ARGS"]))

    args = parser.parse_args()

    if args.list_checks:
        print("%-22s %-8s %s" % ("check", "weight", "profiles"))
        for name in ALL_CHECKS:
            profiles = ",".join(sorted(key for key, value in PROFILES.items()
                                       if name in value["enabled"]))
            print("%-22s %-8.1f %s" % (name, DEFAULT_WEIGHTS[name], profiles))
        return 0

    try:
        cfg = build_config(args)
    except ConfigError as exc:
        err("prose-lint: %s" % exc)
        return 2
    results = []
    for path in args.filenames:
        if any(fnmatch.fnmatch(path, pattern) for pattern in args.exclude or []):
            continue
        kind, syntax = classify(path, args.include_unknown)
        if kind is None:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except (IOError, OSError) as exc:
            err("%s: cannot read (%s)" % (path, exc))
            return 2
        results.append(evaluate(path, text, cfg, kind, syntax))

    if args.as_json:
        payload = [{
            "path": r["path"], "kind": r["kind"], "words": r["words"],
            "weighted": r["weighted"], "rate": r["rate"], "passed": r["passed"],
            "longest_sentence": r["longest_sentence"],
            "is_short": r["is_short"], "short_allowance": r["short_allowance"],
            "counts": r["counts"], "reasons": r["reasons"],
            "findings": [{"line": f.line, "check": f.check, "detail": f.detail,
                          "excerpt": f.excerpt} for f in r["findings"]],
        } for r in results]
        if args.total:
            print(json.dumps({"files": payload, "total": totals(results)},
                             indent=2))
        else:
            print(json.dumps(payload, indent=2))
    else:
        for result in results:
            if not result["passed"] or (args.warn_only and result["findings"]):
                report(result, args.quiet)
        if args.total:
            print_totals(totals(results), cfg)

    failed = [r for r in results if not r["passed"]]
    if failed and args.warn_only:
        err("prose-lint: %d file(s) over budget, not blocking (--warn-only)"
            % len(failed))
        return 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
