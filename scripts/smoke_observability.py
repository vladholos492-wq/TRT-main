#!/usr/bin/env python3
"""
Smoke test for Observability V2: ensures logging doesn't crash.

This script verifies that:
1. Observability V2 module can be imported
2. All log functions can be called without errors
3. Logging doesn't break when handlers are imported
"""

import sys
import os
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Suppress logging during tests
logging.basicConfig(level=logging.CRITICAL)


def test_observability_import() -> bool:
    """Test that observability v2 can be imported."""
    print("Testing observability v2 import...")
    try:
        from app.observability.v2 import (
            log_startup_summary,
            log_boot_result,
            log_webhook_in,
            log_enqueue_ok,
            log_worker_pick,
            log_dispatch_start,
            log_dispatch_ok,
            log_dispatch_fail,
            log_ui_render,
            log_decision,
            log_dependency,
            log_safe_error,
            log_db_observability,
            log_db_degraded,
            log_passive_wait,
            log_deploy_phase,
            log_ready_summary,
        )
        print("Observability v2 import: OK")
        return True
    except Exception as e:
        print(f"Observability v2 import: FAILED")
        print(f"   Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_log_functions() -> bool:
    """Test that all log functions can be called without errors."""
    print("Testing log functions...")
    try:
        from app.observability.v2 import (
            log_startup_summary,
            log_boot_result,
            log_webhook_in,
            log_enqueue_ok,
            log_worker_pick,
            log_dispatch_start,
            log_dispatch_ok,
            log_dispatch_fail,
            log_ui_render,
            log_decision,
            log_dependency,
            log_safe_error,
            log_db_observability,
            log_db_degraded,
            log_passive_wait,
            log_deploy_phase,
            log_ready_summary,
        )
        
        # Test each function with minimal valid parameters
        log_startup_summary(version="test", bot_mode="webhook", port=10000)
        log_boot_result(success=True, reason="test")
        log_webhook_in(cid="test_cid", update_id=1, update_type="message")
        log_enqueue_ok(cid="test_cid", update_id=1, queue_depth=0, queue_max=100)
        log_worker_pick(cid="test_cid", update_id=1, worker_id=0)
        log_dispatch_start(cid="test_cid", update_id=1, handler_name="test_handler")
        log_dispatch_ok(cid="test_cid", update_id=1, handler_name="test_handler", duration_ms=100.0)
        log_dispatch_fail(
            cid="test_cid",
            update_id=1,
            handler_name="test_handler",
            error_type="TestError",
            safe_message="test error",
            duration_ms=50.0,
        )
        log_ui_render(cid="test_cid", screen_id="test_screen", user_id=123)
        log_decision(cid="test_cid", decision_point="test", chosen_branch="branch1")
        log_dependency(cid="test_cid", dependency_type="db", dependency_name="postgres", available=True)
        log_safe_error(
            cid="test_cid",
            error_type="TestError",
            safe_message="test error",
            file_line="test.py:123",
        )
        log_db_observability(pool_config={"maxconn": 10}, read_only_check=True)
        log_db_degraded(cid="test_cid", operation="test", reason="test reason")
        log_passive_wait(lock_holder_pid=123, idle_duration=10.0)
        log_deploy_phase(phase="test", details={"key": "value"})
        log_ready_summary(endpoints=["/health", "/webhook"], webhook_url="https://test.com/webhook")
        
        print("Log functions: OK")
        return True
    except Exception as e:
        print(f"Log functions: FAILED")
        print(f"   Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_handler_imports() -> bool:
    """Test that handlers can be imported without breaking observability."""
    print("Testing handler imports...")
    try:
        # Import main handlers (skip if aiogram not available in dev env)
        try:
            from bot.handlers import admin, flow, marketing, balance, history
            print("Handler imports: OK")
            return True
        except ImportError as e:
            if "aiogram" in str(e).lower():
                print("Handler imports: SKIPPED (aiogram not available in dev env)")
                return True  # Not a failure - just missing dependency
            raise
    except Exception as e:
        print(f"Handler imports: FAILED")
        print(f"   Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main smoke test."""
    print("=" * 60)
    print("SMOKE TEST: Observability V2")
    print("=" * 60)
    print()
    
    all_passed = True
    
    all_passed &= test_observability_import()
    all_passed &= test_log_functions()
    all_passed &= test_handler_imports()
    
    print()
    print("=" * 60)
    if all_passed:
        print("ALL TESTS PASSED - Observability V2 is ready")
        print("=" * 60)
        return 0
    else:
        print("SOME TESTS FAILED - Fix observability before deploy")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())

