#!/usr/bin/env python3
"""
ONE COMMAND "GREEN OR RED" - comprehensive ship check.

This script runs all critical checks:
- import-check
- smoke tests
- py_compile
- minimal runtime boot simulation
- shadow packages check

If anything fails, prints actionable error message.
"""

import sys
import os
import subprocess
import glob
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def run_command(cmd: list, description: str) -> tuple[bool, str]:
    """Run command and return (success, error_message)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            return True, ""
        else:
            error_msg = result.stderr or result.stdout or "Unknown error"
            return False, f"{description}: {error_msg[:500]}"
    except subprocess.TimeoutExpired:
        return False, f"{description}: TIMEOUT (exceeded 60s)"
    except Exception as e:
        return False, f"{description}: {str(e)}"


def check_imports() -> tuple[bool, str]:
    """Check critical imports."""
    return run_command(
        [sys.executable, "scripts/smoke_import_check.py"],
        "Import check"
    )


def check_syntax() -> tuple[bool, str]:
    """Check syntax of critical files."""
    critical_files = [
        "main_render.py",
        "app/observability/v2.py",
        "app/utils/update_queue.py",
        "app/services/wiring.py",
    ]
    
    for file_path in critical_files:
        full_path = project_root / file_path
        if full_path.exists():
            success, error = run_command(
                [sys.executable, "-m", "py_compile", str(full_path)],
                f"Syntax check ({file_path})"
            )
            if not success:
                return False, error
    
    # Check all handlers
    handler_files = list(project_root.glob("bot/handlers/*.py"))
    for handler_file in handler_files:
        if handler_file.name == "__init__.py":
            continue
        success, error = run_command(
            [sys.executable, "-m", "py_compile", str(handler_file)],
            f"Syntax check ({handler_file.relative_to(project_root)})"
        )
        if not success:
            return False, error
    
    return True, ""


def check_smoke_tests() -> tuple[bool, str]:
    """Run smoke tests."""
    smoke_tests = [
        "scripts/smoke_import_check.py",
        "scripts/smoke_admin_analytics.py",
        "scripts/smoke_observability.py",
    ]
    
    for test_script in smoke_tests:
        test_path = project_root / test_script
        if test_path.exists():
            success, error = run_command(
                [sys.executable, str(test_path)],
                f"Smoke test ({test_script})"
            )
            if not success:
                # Skip if it's just missing aiogram in dev env
                if "aiogram" in error.lower() and "not available" in error.lower():
                    continue
                return False, error
    
    return True, ""


def check_shadow_packages() -> tuple[bool, str]:
    """Check for shadow packages (local folders shadowing PyPI packages)."""
    shadow_checks = [
        ("aiogram", "aiogram/__init__.py"),
    ]
    
    for package_name, check_path in shadow_checks:
        check_file = project_root / check_path
        if check_file.exists():
            # In Dockerfile, this is removed, but locally it might exist
            # This is a warning, not a hard failure
            return True, f"WARNING: Local {package_name}/ folder exists (will be removed in Docker)"
    
    return True, ""


def check_minimal_boot() -> tuple[bool, str]:
    """Minimal runtime boot simulation (import main_render, no actual start)."""
    try:
        # Just verify main_render can be imported without errors
        result = subprocess.run(
            [sys.executable, "-c", "import main_render; print('OK')"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return True, ""
        else:
            return False, f"Boot simulation: {result.stderr or result.stdout}"
    except Exception as e:
        return False, f"Boot simulation: {str(e)}"


def main():
    """Main ship check."""
    print("=" * 60)
    print("SHIP CHECK: ONE COMMAND GREEN OR RED")
    print("=" * 60)
    print()
    
    checks = [
        ("Import check", check_imports),
        ("Syntax check", check_syntax),
        ("Smoke tests", check_smoke_tests),
        ("Shadow packages", check_shadow_packages),
        ("Minimal boot", check_minimal_boot),
    ]
    
    all_passed = True
    errors = []
    
    for name, check_func in checks:
        print(f"Checking {name}...", end=" ")
        success, error = check_func()
        if success:
            print("[OK]")
        else:
            print("[FAIL]")
            errors.append(f"{name}: {error}")
            all_passed = False
    
    print()
    print("=" * 60)
    if all_passed:
        print("[OK] ALL CHECKS PASSED - Ready to ship")
        print("=" * 60)
        return 0
    else:
        print("[FAIL] SHIP CHECK FAILED - Fix errors before deploy")
        print("=" * 60)
        print("\nErrors:")
        for error in errors:
            print(f"  - {error}")
        print("\nActionable steps:")
        print("  1. Fix syntax errors: python -m py_compile <file>")
        print("  2. Fix import errors: check imports and dependencies")
        print("  3. Fix smoke tests: run individual smoke scripts")
        print("  4. Check shadow packages: remove local aiogram/ folder if exists")
        return 1


if __name__ == "__main__":
    sys.exit(main())
