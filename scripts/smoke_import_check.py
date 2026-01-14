#!/usr/bin/env python3
"""
Smoke test for critical imports - ensures no ImportError on startup.

This script must pass before any deploy. It verifies that all critical modules
can be imported without circular dependencies or missing symbols.
"""

import sys
import traceback

def test_import(module_name: str, description: str) -> bool:
    """Test importing a module and return True if successful."""
    try:
        __import__(module_name)
        print(f"[OK] {description}: OK")
        return True
    except ImportError as e:
        print(f"[FAIL] {description}: FAILED")
        print(f"   Error: {e}")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"⚠️  {description}: UNEXPECTED ERROR")
        print(f"   Error: {e}")
        traceback.print_exc()
        return False


def test_import_from(module_name: str, symbol_name: str, description: str) -> bool:
    """Test importing a specific symbol from a module."""
    try:
        module = __import__(module_name, fromlist=[symbol_name])
        if hasattr(module, symbol_name):
            getattr(module, symbol_name)
            print(f"✅ {description}: OK")
            return True
        else:
            print(f"[FAIL] {description}: Symbol '{symbol_name}' not found in module")
            return False
    except ImportError as e:
        print(f"[FAIL] {description}: FAILED")
        print(f"   Error: {e}")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"⚠️  {description}: UNEXPECTED ERROR")
        print(f"   Error: {e}")
        traceback.print_exc()
        return False


def main():
    """Run all import tests."""
    print("=" * 60)
    print("SMOKE TEST: Critical Imports")
    print("=" * 60)
    print()
    
    all_passed = True
    
    # Test core modules
    all_passed &= test_import("main_render", "main_render module")
    
    # Test telemetry package imports (must be fail-open)
    all_passed &= test_import("app.telemetry", "app.telemetry package")
    all_passed &= test_import("app.telemetry.utils", "app.telemetry.utils (pure utilities)")
    all_passed &= test_import("app.telemetry.telemetry_helpers", "app.telemetry.telemetry_helpers")
    all_passed &= test_import("app.telemetry.middleware", "app.telemetry.middleware")
    
    # Test logging_config import (critical for boot)
    try:
        from app.telemetry.logging_config import configure_logging
        print("[OK] app.telemetry.logging_config.configure_logging: OK")
    except Exception as e:
        print(f"[FAIL] app.telemetry.logging_config.configure_logging: FAILED")
        print(f"   Error: {e}")
        traceback.print_exc()
        all_passed = False
    
    # Test all bot handlers (critical for boot)
    print()
    print("=" * 60)
    print("Testing bot handlers (must import without errors)")
    print("=" * 60)
    print()
    
    handler_modules = [
        "bot.handlers.marketing",
        "bot.handlers.flow",
        "bot.handlers.quick_actions",
        "bot.handlers.history",
        "bot.handlers.gallery",
    ]
    
    for module in handler_modules:
        all_passed &= test_import(module, f"{module} handler")
    
    print()
    print("=" * 60)
    print("Testing legacy telemetry symbols (must exist as stubs)")
    print("=" * 60)
    print()
    
    # Test legacy telemetry symbols (must exist as stubs)
    legacy_symbols = [
        "log_callback_received",
        "log_callback_routed",
        "log_callback_accepted",
        "log_callback_rejected",
        "log_callback_processed",
        "log_callback_error",
        "log_ui_render",
        "log_event",
        "get_update_id",
        "get_user_id",
        "get_chat_id",
        "get_message_id",
        "get_callback_id",
        "TelemetryMiddleware",
    ]
    
    for symbol in legacy_symbols:
        all_passed &= test_import_from(
            "app.telemetry.telemetry_helpers",
            symbol,
            f"app.telemetry.telemetry_helpers.{symbol}"
        )
    
    print()
    print("=" * 60)
    if all_passed:
        print("[PASS] ALL TESTS PASSED - Imports are clean")
        print("=" * 60)
        return 0
    else:
        print("[FAIL] SOME TESTS FAILED - Fix imports before deploy")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())

