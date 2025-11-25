#!/usr/bin/env python3
"""Pre-commit hook to ensure decorators include required keyword arguments.

This hook checks Python decorators to ensure they include specified required
keyword arguments.

Configuration:
    The hook accepts configuration via --config argument, environment variable
    DECORATOR_CHECK_CONFIG, or defaults to checking task.kubernetes for 'name'.

    Supported formats:
    1. JSON string: '{"task.kubernetes": ["name"], "other.decorator": ["arg1", "arg2"]}'
    2. JSON file path: Path to a JSON file with the same structure
    3. Simple format: 'task.kubernetes:name;other.decorator:arg1,arg2'

    Example configurations:
        JSON: '{"task.kubernetes": ["name"]}'
        Simple: 'task.kubernetes:name;task.docker:image,name'

Usage:
    python3 decorator_kwargs.py --config '{"task.kubernetes": ["name"]}' file1.py file2.py
"""
import ast
import json
import os
import subprocess
import sys

from pathlib import Path


class DecoratorChecker(ast.NodeVisitor):
    """AST visitor to check decorators for missing required keyword arguments.

    This class traverses Python AST to find function decorators and verifies
    that they include all required keyword arguments as specified in the
    decorator configuration.

    Attributes:
        file_path: Path to the file being checked (for error reporting)
        decorator_config: Dictionary mapping decorator paths to lists of required kwargs
        errors: List of error messages found during checking
    """

    def __init__(self, file_path, decorator_config):
        """Initialize checker with decorator configuration.

        Args:
            file_path: Path to the file being checked (used in error messages)
            decorator_config: Dictionary mapping decorator paths to lists of required kwargs.
                             Keys are decorator paths like "task.kubernetes" or "decorator".
                             Values are lists of required keyword argument names.
                             Example: {"task.kubernetes": ["name"], "other.decorator": ["arg1", "arg2"]}
        """
        self.file_path = file_path
        self.decorator_config = decorator_config
        self.errors = []

    def _get_decorator_path(self, decorator):
        """Extract the full path string for a decorator from AST.

        Converts AST decorator nodes into their string representation.
        Handles simple names, attribute access, and nested attributes.

        Args:
            decorator: AST Call node representing the decorator

        Returns:
            String representation of the decorator path (e.g., "task.kubernetes",
            "module.submodule.decorator"), or None if the decorator structure
            cannot be determined.

        Examples:
            @task.kubernetes(...) -> "task.kubernetes"
            @decorator(...) -> "decorator"
            @module.task.kubernetes(...) -> "module.task.kubernetes"
        """
        if isinstance(decorator.func, ast.Attribute):
            if isinstance(decorator.func.value, ast.Name):
                return f"{decorator.func.value.id}.{decorator.func.attr}"
            elif isinstance(decorator.func.value, ast.Attribute):
                # Handle nested attributes like module.task.kubernetes
                parts = []
                node = decorator.func.value
                while isinstance(node, ast.Attribute):
                    parts.append(node.attr)
                    node = node.value
                if isinstance(node, ast.Name):
                    parts.append(node.id)
                parts.append(decorator.func.attr)
                return ".".join(reversed(parts))
        elif isinstance(decorator.func, ast.Name):
            return decorator.func.id
        return None

    def visit_FunctionDef(self, node):
        """Visit function definition nodes to check their decorators.

        This method is called by the AST visitor for each function definition.
        It checks all decorators on the function against the decorator_config
        to ensure required keyword arguments are present.

        Args:
            node: AST FunctionDef node representing a function definition
        """
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                decorator_path = self._get_decorator_path(decorator)
                if decorator_path and decorator_path in self.decorator_config:
                    required_kwargs = self.decorator_config[decorator_path]
                    # Get all keyword argument names present in the decorator
                    present_kwargs = {
                        kw.arg
                        for kw in decorator.keywords
                        if isinstance(kw, ast.keyword) and kw.arg is not None
                    }
                    # Check for missing required kwargs
                    missing_kwargs = [
                        kw for kw in required_kwargs if kw not in present_kwargs
                    ]
                    if missing_kwargs:
                        lineno = decorator.lineno
                        col_offset = decorator.col_offset
                        missing_str = ", ".join(f"{kw}=" for kw in missing_kwargs)
                        self.errors.append(
                            f"{self.file_path}:{lineno}:{col_offset}: "
                            f"{decorator_path}() decorator is missing required keyword argument(s): {missing_str}"
                        )
        # Continue visiting child nodes
        self.generic_visit(node)


def load_config(config_str_or_path):
    """Load decorator configuration from various formats.

    Attempts to load configuration in the following order:
    1. Parse as JSON string
    2. Load from file path (if file exists)
    3. Parse as simple format: "decorator:kwarg1,kwarg2;decorator2:kwarg1"
    4. Return default configuration if config_str_or_path is None/empty

    Args:
        config_str_or_path: Configuration as JSON string, file path, simple format,
                           or None/empty for default config

    Returns:
        Dictionary mapping decorator paths to lists of required keyword arguments.
        Example: {"task.kubernetes": ["name"], "other.decorator": ["arg1", "arg2"]}

    Raises:
        SystemExit: If configuration cannot be parsed and no default is available

    Examples:
        JSON string: '{"task.kubernetes": ["name"]}'
        File path: '.decorator-config.json'
        Simple format: 'task.kubernetes:name;other.decorator:arg1,arg2'
        None/empty: Returns default {"task.kubernetes": ["name"]}
    """
    if not config_str_or_path:
        # Default configuration for backward compatibility
        return {"task.kubernetes": ["name"]}

    # Try to parse as JSON string first
    try:
        return json.loads(config_str_or_path)
    except (json.JSONDecodeError, TypeError):
        pass

    # Try to load as file path
    config_path = Path(config_str_or_path)
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"Error loading config from {config_path}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)

    # If neither worked, try to parse as simple format: "decorator:kwarg1,kwarg2;decorator2:kwarg1"
    # This is a fallback for simpler command-line usage
    try:
        config = {}
        for item in config_str_or_path.split(";"):
            if ":" in item:
                decorator, kwargs_str = item.split(":", 1)
                decorator = decorator.strip()
                kwargs = [kw.strip() for kw in kwargs_str.split(",") if kw.strip()]
                if decorator and kwargs:
                    config[decorator] = kwargs
        if config:
            return config
    except Exception:
        pass

    print(
        f"Error: Could not parse config '{config_str_or_path}'. "
        f"Expected JSON string, file path, or format 'decorator:kwarg1,kwarg2;decorator2:kwarg1'",
        file=sys.stderr,
    )
    sys.exit(1)


def check_file(file_path, decorator_config):
    """Check a single Python file for decorator violations.

    Parses the Python file and checks all function decorators against the
    provided configuration to ensure required keyword arguments are present.

    Args:
        file_path: Path to the Python file to check
        decorator_config: Dictionary mapping decorator paths to lists of required kwargs

    Returns:
        List of error messages. Empty list if no violations found.
        Each error message includes file path, line number, column offset, and
        details about missing keyword arguments.

    Note:
        Files with syntax errors are silently skipped (other tools will catch these).
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, IOError) as e:
        return [f"{file_path}: Error reading file: {e}"]

    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        # Skip files with syntax errors (other tools will catch these)
        return []

    checker = DecoratorChecker(file_path, decorator_config)
    checker.visit(tree)
    return checker.errors


def get_staged_python_files():
    """Get staged Python files from git.

    Returns:
        List of Path objects for staged Python files.
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        stdout=subprocess.PIPE,
        check=False,
    )

    if result.returncode != 0:
        return []

    files = []
    for line in result.stdout.decode("utf-8").split("\n"):
        line = line.strip()
        if line and line.endswith(".py"):
            files.append(Path(line))

    return files


def main():
    """Entry point for the pre-commit hook.

    Parses command-line arguments, loads decorator configuration, and checks
    all provided Python files (or staged Python files if none provided) for
    decorator violations.

    Command-line arguments:
        files: Optional list of Python files to check. If not provided, checks
              all staged Python files from git.
        --config: Optional decorator configuration (JSON string, file path, or simple format)
                 If not provided, checks DECORATOR_CHECK_CONFIG environment variable.
                 If neither provided, uses default configuration.

    Exit codes:
        0: No violations found
        1: One or more violations found (errors printed to stdout)
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Check decorators for required keyword arguments"
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Python files to check (if not provided, checks staged Python files)",
    )
    parser.add_argument(
        "--config",
        help=(
            "Decorator configuration as JSON string, file path, or simple format. "
            'Example JSON: \'{"task.kubernetes": ["name"]}\'. '
            "Example simple: 'task.kubernetes:name;other.decorator:arg1,arg2'. "
            "Can also be set via DECORATOR_CHECK_CONFIG environment variable."
        ),
        default=None,
    )
    args = parser.parse_args()

    # Load config from args or environment variable
    config_str = args.config or os.environ.get("DECORATOR_CHECK_CONFIG")
    decorator_config = load_config(config_str)

    # Get files to check: use provided files or get staged Python files from git
    if args.files:
        files_to_check = [Path(f) for f in args.files]
    else:
        files_to_check = get_staged_python_files()

    if not files_to_check:
        # No files to check, exit successfully
        sys.exit(0)

    errors = []
    for file_path in files_to_check:
        if not file_path.exists():
            continue
        if file_path.suffix != ".py":
            continue
        errors.extend(check_file(file_path, decorator_config))

    if errors:
        print("\n".join(errors))
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
