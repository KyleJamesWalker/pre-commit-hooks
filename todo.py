#!/usr/bin/env python3

"""Pre-commit hook to error on TODOs without matching a ticket directly afterwards."""
import argparse
import os
import re
import sys


def err(s: str) -> None:
    """Print a string to stderr."""
    print(s, file=sys.stderr)


def main():
    """Entry point for the pre-commit hook."""
    matches = []
    return_val = 0

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--search-pattern",
        default=r"^.*TODO:(?!\s*\[?[A-Z]{1,5}-\d+).*$",
    )
    parser.add_argument("--repo-skip-pattern", default=".*-template-.*")
    parser.add_argument(
        "--found-message",
        default="Search pattern found. Please remove or add tracking ticket.",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help=(
            "Report matches as warnings and exit 0 instead of failing. Also scans "
            "repos that match --repo-skip-pattern, so template repos can surface the "
            "TODOs that will start blocking once the hook enforces normally."
        ),
    )
    parser.add_argument("filenames", nargs="*")
    args = parser.parse_args()

    skip_repo = re.search(args.repo_skip_pattern, os.getcwd().split(os.sep)[-1])
    # Normally a skip-pattern (template) repo does nothing. --warn-only overrides
    # that so matches are still surfaced for visibility, just never block.
    if skip_repo and not args.warn_only:
        # Skip the hook when requested for template repos.
        pass
    else:
        matcher = re.compile(args.search_pattern)
        for filename in args.filenames:
            with open(filename, "r") as file:
                try:
                    for line_num, line in enumerate(file, start=1):
                        if matcher.match(line):
                            matches.append((filename, line_num, line.lstrip().rstrip()))
                except UnicodeDecodeError:
                    err(f"Warning: Error decoding {filename}")
                    continue

        if matches:
            err(f"{'Warning' if args.warn_only else 'Error'}: {args.found_message}")
            for match in matches:
                err(f"  {match[0]}:{match[1]} - {match[2]}")
            err("")
            return_val = 0 if args.warn_only else 1

    return return_val


if __name__ == "__main__":
    sys.exit(main())
