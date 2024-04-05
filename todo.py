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
    parser.add_argument("filenames", nargs="*")
    args = parser.parse_args()

    if re.search(args.repo_skip_pattern, os.getcwd().split(os.sep)[-1]):
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
            err("Error: Search pattern found. Please remove or add tracking ticket.")
            for match in matches:
                err(f"  {match[0]}:{match[1]} - {match[2]}")
            err("")
            return_val = 1

    return return_val


if __name__ == "__main__":
    sys.exit(main())
