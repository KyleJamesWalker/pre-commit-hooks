#!/usr/bin/env python3

"""Pre-commit hook to verify generated sidecars are updated based on rules."""
import argparse
import datetime
import os
import re
import subprocess
import sys
import shlex

from collections import namedtuple

# Named tuple to store the status each file
FileStatus = namedtuple("FileStatus", ["status", "filename"])


def err(s: str) -> None:
    """Print a string to stderr."""
    print(s, file=sys.stderr)


def get_commit_files() -> list:
    """Get the current staged files for the commit.

    Responses from `git status -s`:
        M: The file is modified.
        A: The file has been added to the staging area.
        D: The file has been deleted.
        R: The file has been renamed.
        C: The file has been copied.
        U: The file is unmerged. There are conflicts that need to be resolved.
        ?: The file is untracked.
        !: The file is ignored.

    """
    files = []
    result = subprocess.run(
        ["git", "status", "-s"], stdout=subprocess.PIPE, check=False
    )

    if result.returncode == 0:
        # git status -s format is XY<space>filename; strip both parts cleanly
        files = [
            FileStatus(x[:2].strip(), x[3:])
            for x in result.stdout.decode("utf-8").split("\n")
            if x.strip()
        ]
    else:
        err("Error: Unable to get the current commit files.")

    return files


def check_status(search_file: str, search_status: str, commit_files: list) -> bool:
    """Check if the file is in the commit files with the status."""
    return any(
        file.filename == search_file and file.status in search_status
        for file in commit_files
    )


def sidecar_checks(commit_files: list, sidecar_rules: list) -> int:
    """Check if the sidecar files are updated based on the rules provided."""
    result = 0
    for rule in sidecar_rules:
        primary_file, sidecar_file = rule.split(":")
        if check_status(primary_file, "MA", commit_files):
            if not check_status(sidecar_file, "MA", commit_files):
                err(f"Error: {sidecar_file} is not staged with {primary_file}.")
                result += 1

    return result


def parse_time_string(time_string):
    """Parse time strings like 5d3h2m into a timedelta object."""
    match = re.findall(r"(\d+)([smhdwMy])", time_string)
    if match:
        total_time = datetime.timedelta()
        for amount, unit in match:
            amount = int(amount)
            if unit == "s":
                total_time += datetime.timedelta(seconds=amount)
            elif unit == "m":
                total_time += datetime.timedelta(minutes=amount)
            elif unit == "h":
                total_time += datetime.timedelta(hours=amount)
            elif unit == "d":
                total_time += datetime.timedelta(days=amount)
            elif unit == "w":
                total_time += datetime.timedelta(weeks=amount)
            elif unit == "M":
                total_time += datetime.timedelta(days=amount * 30)
            elif unit == "y":
                total_time += datetime.timedelta(days=amount * 365)
        return total_time
    else:
        raise ValueError(f"Invalid time string: {time_string}")


def get_commit_time(filename: str) -> datetime.datetime | None:
    """Get the last commit time for a file from git history."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", filename],
        stdout=subprocess.PIPE,
        check=False,
    )
    if result.returncode == 0:
        timestamp = result.stdout.decode("utf-8").strip()
        if timestamp:
            return datetime.datetime.fromtimestamp(int(timestamp))
    return None


def get_file_age(filename: str, source: str) -> datetime.timedelta | None:
    """Get the age of a file based on the source type.

    Args:
        filename: Path to the file.
        source: One of "commit" (git log) or "mtime" (filesystem modification time).

    Returns:
        A timedelta representing the file's age, or None if the age
        could not be determined.
    """
    now = datetime.datetime.now()
    if source == "commit":
        commit_time = get_commit_time(filename)
        if commit_time is None:
            err(f"Warning: No git history for {filename}, falling back to mtime.")
            return now - datetime.datetime.fromtimestamp(os.path.getmtime(filename))
        return now - commit_time
    else:
        return now - datetime.datetime.fromtimestamp(os.path.getmtime(filename))


def age_checks(age_rules: list, commit_files: list) -> int:
    """Check if the sidecar files are updated based on the rules provided.

    Rule format: filename:age[:source]
        source is "commit" (default) or "mtime".
    """
    result = 0
    for rule in age_rules:
        parts = rule.split(":")
        if len(parts) == 3:
            filename, age, source = parts
        elif len(parts) == 2:
            filename, age = parts
            source = "commit"
        else:
            err(f"Error: Invalid age rule: {rule}")
            result += 1
            continue

        if source not in ("commit", "mtime"):
            err(f"Error: Invalid age source '{source}', expected 'commit' or 'mtime'.")
            result += 1
            continue

        if check_status(filename, "MA", commit_files):
            continue

        max_age = parse_time_string(age)
        file_age = get_file_age(filename, source)
        if file_age is not None and file_age > max_age:
            err(f"Error: {filename} is older than {max_age} (source: {source}).")
            result += 1
    return result


def main():
    """Entry point for the pre-commit hook."""
    return_val = 0

    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", action="append")
    parser.add_argument("--age", action="append")

    # Allow pre-commit try-repo to pass in additional arguments
    if os.environ.get("PRE_COMMIT_TRY_ARGS"):
        sys.argv.extend(shlex.split(os.environ["PRE_COMMIT_TRY_ARGS"]))

    args = parser.parse_args()

    if args.sidecar is None and args.age is None:
        err("Error: No rules provided.")
        return 1

    commit_files = get_commit_files()

    if args.sidecar:
        return_val += sidecar_checks(commit_files, args.sidecar)

    if args.age:
        return_val += age_checks(args.age, commit_files)

    return return_val


if __name__ == "__main__":
    sys.exit(main())
