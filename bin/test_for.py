#!/usr/bin/env python3
"""
Incremental test selection tool for Fenix.

Analyzes Python import chains to determine which tests are affected by
changes to specific files. Uses AST parsing for accurate analysis.

Usage:
    python3 bin/test_for.py <file1> [file2 ...]     # Run affected tests
    python3 bin/test_for.py --dry-run <file1> ...    # List tests without running
    python3 bin/test_for.py --all                     # Run all tests
"""

import ast
import os
import sys
import yaml
from pathlib import Path
from typing import Set, Dict, List, Optional
import subprocess


def normalize_module_path(file_path: str) -> str:
    """Convert file path to Python module path."""
    # Remove .py extension
    path = Path(file_path)
    if path.suffix == '.py':
        path = path.with_suffix('')
    
    # Convert to module path (replace / with .)
    parts = list(path.parts)
    
    # Remove common prefixes
    if 'core' in parts:
        idx = parts.index('core')
        parts = parts[idx:]
    elif 'tests' in parts:
        idx = parts.index('tests')
        parts = parts[idx:]
    
    return '.'.join(parts)


def extract_imports_from_file(file_path: str) -> Set[str]:
    """Extract all imports from a Python file using AST."""
    imports = set()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content, filename=file_path)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
    
    return imports


def build_import_graph(tests_dir: str) -> Dict[str, Set[str]]:
    """Build import graph for all test files."""
    graph = {}
    
    for py_file in Path(tests_dir).glob('*.py'):
        if py_file.name.startswith('_'):
            continue
        
        imports = extract_imports_from_file(str(py_file))
        module_path = f"tests.{py_file.stem}"
        graph[module_path] = imports
    
    return graph


def find_affected_tests(target_module: str, import_graph: Dict[str, Set[str]],
                       max_depth: int = 3) -> Set[str]:
    """Find tests affected by changes to target module.

    Uses BFS to traverse import chain up to max_depth levels.
    Handles partial matches (e.g., core.pm_engine.dispatch matches core.pm_engine).
    """
    affected = set()
    queue = [(target_module, 0)]
    visited = set()

    while queue:
        module, depth = queue.pop(0)

        if module in visited or depth > max_depth:
            continue

        visited.add(module)

        # Check if any test imports this module (or a parent module)
        for test_module, imports in import_graph.items():
            # Check for exact match or partial match (parent module)
            for imp in imports:
                if module == imp or module.startswith(imp + '.') or imp.startswith(module + '.'):
                    affected.add(test_module)
                    # Also check transitive imports
                    if depth < max_depth:
                        queue.append((test_module, depth + 1))
                    break

    return affected


def load_test_map(tests_dir: str) -> Dict[str, str]:
    """Load explicit test mappings from test_map.yaml."""
    map_file = Path(tests_dir) / "test_map.yaml"
    
    if not map_file.exists():
        return {}
    
    try:
        with open(map_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if not data or 'explicit' not in data:
            return {}
        
        return data['explicit']
    except Exception as e:
        print(f"Warning: Could not load test_map.yaml: {e}", file=sys.stderr)
        return {}


def apply_explicit_mappings(target_files: List[str], explicit_map: Dict[str, str]) -> Set[str]:
    """Apply explicit test mappings for files without import relationships."""
    affected = set()

    for target_file in target_files:
        # Normalize path
        target_path = Path(target_file)
        target_str = str(target_path)

        for pattern, test_file in explicit_map.items():
            # Check if target matches pattern (prefix or exact match)
            if target_str.startswith(pattern) or target_str == pattern:
                affected.add(test_file)

    return affected


def run_tests(test_files: List[str], dry_run: bool = False) -> bool:
    """Run the specified test files."""
    if not test_files:
        print("No tests affected. Consider running full test suite.")
        return True
    
    if dry_run:
        print("Tests that would be run:")
        for test_file in sorted(test_files):
            print(f"  {test_file}")
        return True
    
    # Run pytest with selected test files
    cmd = [sys.executable, "-m", "pytest", "-v"] + test_files
    print(f"Running: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, cwd=Path(__file__).resolve().parent.parent)
    return result.returncode == 0


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    # Parse arguments
    dry_run = False
    run_all = False
    target_files = []
    
    for arg in sys.argv[1:]:
        if arg == '--dry-run':
            dry_run = True
        elif arg == '--all':
            run_all = True
        else:
            target_files.append(arg)
    
    # Get project root
    project_root = Path(__file__).resolve().parent.parent
    tests_dir = project_root / "tests"
    
    if run_all:
        print("Running all tests...")
        cmd = [sys.executable, "-m", "pytest", "-v", str(tests_dir)]
        result = subprocess.run(cmd, cwd=project_root)
        sys.exit(result.returncode)
    
    if not target_files:
        print("Error: No files specified. Use --all to run all tests.")
        sys.exit(1)
    
    # Build import graph
    print("Analyzing import chains...")
    import_graph = build_import_graph(str(tests_dir))
    
    # Find affected tests
    affected_tests = set()
    
    for target_file in target_files:
        # Convert to module path
        target_module = normalize_module_path(target_file)
        
        # Find tests through import analysis
        tests = find_affected_tests(target_module, import_graph)
        affected_tests.update(tests)
    
    # Apply explicit mappings
    explicit_map = load_test_map(str(tests_dir))
    explicit_tests = apply_explicit_mappings(target_files, explicit_map)
    # Convert explicit test paths to module paths for consistency
    for test_path in explicit_tests:
        # Convert "tests/test_foo.py" to "tests.test_foo"
        if test_path.startswith("tests/"):
            module_path = "tests." + test_path[6:].replace("/", ".").replace(".py", "")
            affected_tests.add(module_path)
        elif test_path.startswith("tests."):
            affected_tests.add(test_path)

    # Convert module paths to file paths
    test_files = []
    for test_module in affected_tests:
        if test_module.startswith('tests.'):
            test_file = tests_dir / f"{test_module[6:]}.py"
            if test_file.exists():
                test_files.append(str(test_file))
    
    # Run tests
    success = run_tests(test_files, dry_run)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
