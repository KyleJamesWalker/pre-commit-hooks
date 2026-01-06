#!/usr/bin/env python3
r"""Validate that two or more YAML files are synchronized according to rules.

This hook can validate any YAML structure. It supports
both JSON configuration files and simple command-line arguments.

Files are specified as pairs of (file_path yaml_path). The script validates
all pairs of files to ensure they are synchronized.

Configuration is provided via JSON with validation rules:
- tag_match: Extract and compare image tags (e.g., "image:tag" -> compare "tag")
- exact_match: Values must be exactly equal
- regex_match: Values must match a regex pattern (can extract groups for comparison)
- no_validation: Skip validation (allow any differences)

JSON format:
{
  "rules": [
    {
      "keys": ["IMAGE"],
      "type": "tag_match"
    },
    {
      "keys": ["*"],
      "type": "exact_match"
    }
  ]
}

Simple format (via args):
  file1.yaml path1 file2.yaml path2 [file3.yaml path3 ...]
  --tag-match=IMAGE
  --exact-match=*
  --no-validation=KEY1,KEY2

All keys must match 100% between all files.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml


def extract_image_tag(image_string: str) -> str:
    """Extract the tag from an image string (e.g., 'image:tag' -> 'tag')."""
    # Remove quotes if present
    image_string = image_string.strip("\"'")
    # Extract tag after the last colon
    if ":" in image_string:
        return image_string.split(":")[-1]
    return ""


def get_nested_value(data: Any, path: str) -> Any:
    """
    Get a nested value from a dictionary using dot notation.
    Supports array indexing like 'containers[0]'.

    Examples:
        get_nested_value(data, "configMapData") -> data["configMapData"]
        get_nested_value(data, "spec.template.spec") -> data["spec"]["template"]["spec"]
        get_nested_value(data, "containers[0].env") -> data["containers"][0]["env"]
    """
    if not path:
        return data

    parts = re.split(r"(\[.*?\])", path)
    current = data

    for part in parts:
        if not part:
            continue
        if part.startswith("[") and part.endswith("]"):
            # Array index
            index = int(part[1:-1])
            if not isinstance(current, (list, tuple)):
                raise ValueError(f"Path '{path}': Expected list at '{part}', got {type(current).__name__}")
            if index >= len(current):
                raise ValueError(f"Path '{path}': Index {index} out of range for list of length {len(current)}")
            current = current[index]
        else:
            # Dictionary key
            if not isinstance(current, dict):
                raise ValueError(f"Path '{path}': Expected dict at '{part}', got {type(current).__name__}")
            if part not in current:
                raise ValueError(f"Path '{path}': Key '{part}' not found")
            current = current[part]

    return current


def get_yaml_data(yaml_data: dict, yaml_path: str) -> Dict[str, str]:
    """
    Extract data from YAML structure.

    Args:
        yaml_data: The parsed YAML data
        yaml_path: Dot-notation path to the data (e.g., "configMapData", "data", "spec.env")
                   Use empty string "" to use root level

    Returns:
        Dictionary of key-value pairs
    """
    try:
        data = get_nested_value(yaml_data, yaml_path)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ValueError(f"Could not extract data from path '{yaml_path}': {e}")

    if not isinstance(data, dict):
        raise ValueError(f"Expected dictionary at path '{yaml_path}', got {type(data).__name__}")

    # Ensure all values are strings (convert if needed)
    result = {}
    for key, value in data.items():
        if value is None:
            result[key] = ""
        elif isinstance(value, (dict, list)):
            raise ValueError(f"Key '{key}' has non-scalar value. Only string values are supported.")
        else:
            result[key] = str(value)

    return result


def parse_simple_rules(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """Parse simple command-line arguments into rule format."""
    rules = []

    # Tag match rules
    if args.tag_match:
        for keys_str in args.tag_match:
            keys = [k.strip() for k in keys_str.split(",") if k.strip()]
            if keys:
                rules.append({"keys": keys, "type": "tag_match"})

    # Exact match rules
    if args.exact_match:
        for keys_str in args.exact_match:
            keys = [k.strip() for k in keys_str.split(",") if k.strip()]
            if keys:
                rules.append({"keys": keys, "type": "exact_match"})

    # Regex match rules
    if args.regex_match:
        for rule_str in args.regex_match:
            # Format: "KEY1,KEY2:pattern:group" or "KEY1,KEY2:pattern"
            parts = rule_str.split(":", 2)
            if len(parts) < 2:
                raise ValueError(f"Invalid regex_match format: '{rule_str}'. Expected 'KEYS:PATTERN[:GROUP]'")
            keys = [k.strip() for k in parts[0].split(",") if k.strip()]
            pattern = parts[1]
            extract_group = 0
            if len(parts) > 2 and parts[2]:
                try:
                    extract_group = int(parts[2])
                except ValueError:
                    raise ValueError(f"Invalid regex_match format: '{rule_str}'. GROUP must be an integer, got '{parts[2]}'")
            if keys:
                rules.append({
                    "keys": keys,
                    "type": "regex_match",
                    "pattern": pattern,
                    "extract_group": extract_group,
                })

    # No validation rules
    if args.no_validation:
        for keys_str in args.no_validation:
            keys = [k.strip() for k in keys_str.split(",") if k.strip()]
            if keys:
                rules.append({"keys": keys, "type": "no_validation"})

    return rules


def load_rules(config: Dict[str, Any]) -> tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    """
    Load and validate rules from JSON configuration.

    Returns:
        (rules, yaml_path, yaml_path2)
    """
    yaml_path = config.get("yaml_path")
    yaml_path2 = config.get("yaml_path2")

    if "rules" not in config:
        raise ValueError("JSON config must have a 'rules' key")

    rules = config["rules"]
    if not isinstance(rules, list):
        raise ValueError("'rules' must be a list")

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"Rule {i} must be a dictionary")
        if "keys" not in rule:
            raise ValueError(f"Rule {i} must have a 'keys' field")
        if "type" not in rule:
            raise ValueError(f"Rule {i} must have a 'type' field")

        rule_type = rule["type"]
        valid_types = ["tag_match", "exact_match", "regex_match", "no_validation"]
        if rule_type not in valid_types:
            raise ValueError(
                f"Rule {i} has invalid type '{rule_type}'. "
                f"Must be one of: {', '.join(valid_types)}"
            )

        if rule_type == "regex_match":
            if "pattern" not in rule:
                raise ValueError(
                    f"Rule {i} with type 'regex_match' must have a 'pattern' field"
                )

    return rules, yaml_path, yaml_path2


def get_keys_for_rule(rule: Dict[str, Any], all_keys: Set[str]) -> Set[str]:
    """Get the set of keys that match a rule."""
    rule_keys = rule["keys"]
    if not isinstance(rule_keys, list):
        raise ValueError("Rule 'keys' must be a list")

    # Handle wildcard
    if "*" in rule_keys:
        return all_keys

    # Return intersection of rule keys and all keys
    return set(rule_keys) & all_keys


def validate_value(
    key: str,
    value1: str,
    value2: str,
    rule: Dict[str, Any],
    file1_name: str,
    file2_name: str,
) -> List[str]:
    """Validate a single key-value pair according to the rule."""
    errors = []
    rule_type = rule["type"]

    if rule_type == "no_validation":
        # No validation needed
        return errors

    if rule_type == "tag_match":
        tag1 = extract_image_tag(value1)
        tag2 = extract_image_tag(value2)
        if tag1 != tag2:
            errors.append(
                f"Key '{key}': Tags do not match - {file1_name} has tag '{tag1}', "
                f"{file2_name} has tag '{tag2}'"
            )

    elif rule_type == "exact_match":
        if value1 != value2:
            errors.append(
                f"Key '{key}': Values do not match - {file1_name} has '{value1}', "
                f"{file2_name} has '{value2}'"
            )

    elif rule_type == "regex_match":
        pattern = rule["pattern"]
        extract_group = rule.get("extract_group", 0)

        try:
            match1 = re.search(pattern, value1)
            match2 = re.search(pattern, value2)

            if not match1:
                errors.append(
                    f"Key '{key}': Value in {file1_name} does not match regex pattern '{pattern}': '{value1}'"
                )
            elif not match2:
                errors.append(
                    f"Key '{key}': Value in {file2_name} does not match regex pattern '{pattern}': '{value2}'"
                )
            else:
                # Extract the specified group (or full match if extract_group is 0)
                if extract_group == 0:
                    extracted1 = match1.group(0)
                    extracted2 = match2.group(0)
                else:
                    # Verify both matches have enough groups
                    max_groups = max(len(match1.groups()), len(match2.groups()))
                    if extract_group > max_groups:
                        errors.append(
                            f"Key '{key}': Regex pattern only has {max_groups} groups, "
                            f"but extract_group is {extract_group}"
                        )
                        return errors
                    extracted1 = match1.group(extract_group)
                    extracted2 = match2.group(extract_group)

                if extracted1 != extracted2:
                    errors.append(
                        f"Key '{key}': Extracted values do not match - {file1_name} extracted '{extracted1}', "
                        f"{file2_name} extracted '{extracted2}'"
                    )
        except re.error as e:
            errors.append(f"Key '{key}': Invalid regex pattern '{pattern}': {e}")

    return errors


def validate_yaml_pair(
    file1_path: Path,
    file2_path: Path,
    yaml_path1: str,
    yaml_path2: str,
    rules: List[Dict[str, Any]],
) -> List[str]:
    """
    Validate that two YAML files are synchronized according to rules.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Read and parse both YAML files
    try:
        with open(file1_path, "r") as f:
            yaml1 = yaml.safe_load(f)
        with open(file2_path, "r") as f:
            yaml2 = yaml.safe_load(f)
    except Exception as e:
        return [f"Error reading YAML files: {e}"]

    # Extract data from YAML
    try:
        data1 = get_yaml_data(yaml1, yaml_path1)
        data2 = get_yaml_data(yaml2, yaml_path2)
    except ValueError as e:
        return [str(e)]

    # Check that all keys match 100%
    keys1 = set(data1.keys())
    keys2 = set(data2.keys())

    if keys1 != keys2:
        missing_in_file2 = keys1 - keys2
        missing_in_file1 = keys2 - keys1
        if missing_in_file2:
            errors.append(
                f"Keys in {file1_path.name} but not in {file2_path.name}: {sorted(missing_in_file2)}"
            )
        if missing_in_file1:
            errors.append(
                f"Keys in {file2_path.name} but not in {file1_path.name}: {sorted(missing_in_file1)}"
            )
        return errors

    all_keys = keys1

    # Build a mapping of keys to rules
    # Keys are matched to the first rule that includes them
    key_to_rule = {}
    unmatched_keys = set(all_keys)

    for rule in rules:
        rule_keys = get_keys_for_rule(rule, all_keys)
        for key in rule_keys:
            if key in unmatched_keys:
                key_to_rule[key] = rule
                unmatched_keys.remove(key)

    # Warn about unmatched keys (though they should be caught by the wildcard rule)
    if unmatched_keys:
        errors.append(
            f"Keys not matched by any rule: {sorted(unmatched_keys)}. "
            "Add a rule with 'keys': ['*'] to match all remaining keys."
        )
        return errors

    # Validate each key according to its rule
    for key in sorted(all_keys):
        value1 = data1[key]
        value2 = data2[key]
        rule = key_to_rule[key]

        key_errors = validate_value(
            key, value1, value2, rule, file1_path.name, file2_path.name
        )
        errors.extend(key_errors)

    return errors


def validate_yaml_sync(
    file_paths: List[tuple[Path, str]],
    rules: List[Dict[str, Any]],
) -> tuple[bool, list[str]]:
    """
    Validate that multiple YAML files are synchronized according to rules.
    Compares all pairs of files to ensure they're all in sync.

    Args:
        file_paths: List of (file_path, yaml_path) tuples
        rules: Validation rules

    Returns:
        (is_valid, error_messages)
    """
    if len(file_paths) < 2:
        return False, ["At least 2 files are required for validation"]

    errors = []

    # Validate all pairs
    for i in range(len(file_paths)):
        for j in range(i + 1, len(file_paths)):
            file1_path, yaml_path1 = file_paths[i]
            file2_path, yaml_path2 = file_paths[j]

            pair_errors = validate_yaml_pair(
                file1_path, file2_path, yaml_path1, yaml_path2, rules
            )

            # Prefix errors with file pair info
            for error in pair_errors:
                errors.append(f"[{file1_path.name} vs {file2_path.name}] {error}")

    return len(errors) == 0, errors


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Validate that two or more YAML files are synchronized",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:

Using JSON config file:
  %(prog)s file1.yaml path1 file2.yaml path2 --config rules.json

Using JSON string:
  %(prog)s file1.yaml path1 file2.yaml path2 --config '{"rules":[...]}'

Using simple args (no config file needed):
  %(prog)s file1.yaml path1 file2.yaml path2 \\
    --tag-match=IMAGE \\
    --exact-match=* \\
    --no-validation=KEY1,KEY2

Multiple files:
  %(prog)s file1.yaml path1 file2.yaml path2 file3.yaml path3 \\
    --exact-match=*

Using regex match:
  %(prog)s file1.yaml path1 file2.yaml path2 \\
    --regex-match="VERSION:v(\\d+\\.\\d+):1" \\
    --exact-match=*

JSON config format:
{
  "rules": [
    {"keys": ["IMAGE"], "type": "tag_match"},
    {"keys": ["*"], "type": "exact_match"}
  ]
}
        """,
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Pairs of (file_path yaml_path). Must be even number of arguments. "
        "Example: file1.yaml path1 file2.yaml path2 [file3.yaml path3 ...]",
    )

    # Config options (mutually exclusive)
    config_group = parser.add_mutually_exclusive_group()
    config_group.add_argument(
        "--config",
        type=str,
        help="JSON configuration string or path to JSON file with validation rules",
    )

    # Simple args (alternative to --config)
    parser.add_argument(
        "--tag-match",
        action="append",
        help="Comma-separated keys that must have matching tags (e.g., IMAGE). Can be specified multiple times.",
    )
    parser.add_argument(
        "--exact-match",
        action="append",
        help="Comma-separated keys that must match exactly (e.g., KEY1,KEY2 or * for all). Can be specified multiple times.",
    )
    parser.add_argument(
        "--regex-match",
        action="append",
        help="Regex match rule in format 'KEYS:PATTERN[:GROUP]' (e.g., 'VERSION:v(\\d+):1'). Can be specified multiple times.",
    )
    parser.add_argument(
        "--no-validation",
        action="append",
        help="Comma-separated keys to skip validation (e.g., KEY1,KEY2). Can be specified multiple times.",
    )

    args = parser.parse_args()

    # Parse file pairs
    if len(args.files) % 2 != 0:
        print(
            "Error: Must provide pairs of (file_path yaml_path). "
            f"Got {len(args.files)} arguments, expected even number.",
            file=sys.stderr,
        )
        sys.exit(1)

    file_paths = []
    for i in range(0, len(args.files), 2):
        file_path = Path(args.files[i])
        yaml_path = args.files[i + 1]

        if not file_path.exists():
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            sys.exit(1)

        file_paths.append((file_path, yaml_path))

    # Load rules and yaml_path
    if args.config:
        # Load JSON configuration
        try:
            config_path = Path(args.config)
            if config_path.exists():
                # It's a file path
                with open(config_path, "r") as f:
                    config = json.load(f)
            else:
                # Try to parse it as JSON string
                config = json.loads(args.config)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON configuration: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error loading configuration: {e}", file=sys.stderr)
            sys.exit(1)

        # Load and validate rules
        try:
            rules, _, _ = load_rules(config)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Use simple args
        if not any([args.tag_match, args.exact_match, args.regex_match, args.no_validation]):
            print(
                "Error: Must specify either --config or at least one validation rule (--tag-match, --exact-match, etc.)",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            rules = parse_simple_rules(args)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Validate
    is_valid, errors = validate_yaml_sync(file_paths, rules)

    if not is_valid:
        file_names = ", ".join([f.name for f, _ in file_paths])
        print(f"Validation failed for files: {file_names}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)

    file_names = ", ".join([f.name for f, _ in file_paths])
    print(f"Validation passed: {file_names} are synchronized")
    sys.exit(0)


if __name__ == "__main__":
    main()
