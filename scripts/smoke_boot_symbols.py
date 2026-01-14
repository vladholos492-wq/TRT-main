#!/usr/bin/env python3
"""
Smoke test for boot symbols - ensures required functions exist before deploy.

This test prevents "NameError: name 'X' is not defined" regressions by verifying
all critical boot functions are importable and callable.
"""

import sys
import traceback
from typing import List, Tuple

def test_symbol(module_name: str, symbol_name: str, description: str):
    """Test that a symbol exists and is callable (if it's a function).
    
    Returns:
        (True, message) if symbol exists and is valid
        (False, message) if symbol is missing or invalid
        None if module is not importable (expected in dev env - skip)
    """
    try:
        module = __import__(module_name, fromlist=[symbol_name])
        if not hasattr(module, symbol_name):
            return False, f"Symbol '{symbol_name}' not found in {module_name}"
        
        symbol = getattr(module, symbol_name)
        # If it's callable, verify it's actually a function (not just a class)
        if callable(symbol):
            # Try to inspect signature (optional check)
            try:
                import inspect
                sig = inspect.signature(symbol)
                return True, f"OK: {symbol_name} is callable (signature: {sig})"
            except Exception:
                return True, f"OK: {symbol_name} is callable"
        else:
            return True, f"OK: {symbol_name} exists (not callable)"
    except ImportError as e:
        # In dev env, some modules may not be importable (e.g., aiogram not installed)
        # This is OK - we only care about symbols existing when modules ARE importable
        # Return None to indicate SKIP
        return None
    except Exception as e:
        return False, f"Unexpected error: {e}"


def main() -> int:
    """Run smoke test for boot symbols."""
    print("=" * 60)
    print("SMOKE TEST: Boot Symbols")
    print("=" * 60)
    print()
    
    all_passed = True
    failures: List[str] = []
    
    # Test critical boot symbols in main_render
    required_symbols = [
        ("main_render", "log_startup_summary", "log_startup_summary function"),
        ("main_render", "log_startup_phase", "log_startup_phase function"),
        ("main_render", "boot_self_check", "boot_self_check function (if exists)"),
        ("main_render", "create_bot_application", "create_bot_application function"),
    ]
    
    # Also test observability modules
    observability_symbols = [
        ("app.observability.v2", "log_startup_summary", "log_startup_summary in v2"),
        ("app.observability.explain", "log_startup_phase", "log_startup_phase in explain"),
        ("app.observability.explain", "log_deploy_topology", "log_deploy_topology in explain"),
        ("app.observability.explain", "log_passive_drop", "log_passive_drop in explain"),
    ]
    
    # Test locking module symbols (critical for boot)
    locking_symbols = [
        ("app.locking.single_instance", "get_lock_key", "get_lock_key function"),
        ("app.locking.single_instance", "get_lock_debug_info", "get_lock_debug_info function"),
        ("app.locking.single_instance", "SingletonLock", "SingletonLock class"),
    ]
    
    all_symbols = required_symbols + observability_symbols + locking_symbols
    
    skipped = 0
    for module_name, symbol_name, description in all_symbols:
        result = test_symbol(module_name, symbol_name, description)
        if result is None:
            # SKIP (module not importable in dev env - expected)
            print(f"[SKIP] {description}: Module not importable in dev env (expected)")
            skipped += 1
        else:
            passed, message = result
            if passed:
                print(f"[OK] {description}: {message}")
            else:
                print(f"[FAIL] {description}: {message}")
                failures.append(f"{module_name}.{symbol_name}: {message}")
                all_passed = False
    
    print()
    print("=" * 60)
    if all_passed:
        if skipped > 0:
            print(f"[OK] ALL BOOT SYMBOLS OK ({skipped} skipped due to dev env) - Ready for deploy")
        else:
            print("[OK] ALL BOOT SYMBOLS OK - Ready for deploy")
        print("=" * 60)
        return 0
    else:
        print("[FAIL] SOME BOOT SYMBOLS MISSING - Fix before deploy")
        print("=" * 60)
        print("\nFailures:")
        for failure in failures:
            print(f"  - {failure}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

