#!/usr/bin/env python3
"""
Smoke test for admin analytics - ensures fail-open behavior when DB unavailable.

This test verifies that Analytics service and admin handlers gracefully handle
missing db_service without raising uncaught exceptions.
"""

import sys
import os
import traceback
from pathlib import Path
from typing import Dict, Any

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_analytics_without_db() -> bool:
    """Test Analytics service with None db_service."""
    try:
        from app.admin.analytics import Analytics
        
        # Create Analytics with None db_service (fail-open scenario)
        analytics = Analytics(None)
        
        # All methods should return empty structures, not raise exceptions
        import asyncio
        
        async def test_methods():
            # Test all methods
            revenue_stats = await analytics.get_revenue_stats(period_days=30)
            assert isinstance(revenue_stats, dict), "get_revenue_stats should return dict"
            assert revenue_stats.get('total_revenue', 0) == 0, "Should return zero revenue"
            
            activity_stats = await analytics.get_user_activity(period_days=7)
            assert isinstance(activity_stats, dict), "get_user_activity should return dict"
            assert activity_stats.get('total_users', 0) == 0, "Should return zero users"
            
            conversion = await analytics.get_free_to_paid_conversion()
            assert isinstance(conversion, dict), "get_free_to_paid_conversion should return dict"
            assert conversion.get('total_free_users', 0) == 0, "Should return zero free users"
            
            top_models = await analytics.get_top_models(limit=10)
            assert isinstance(top_models, list), "get_top_models should return list"
            assert len(top_models) == 0, "Should return empty list"
            
            error_stats = await analytics.get_error_stats(limit=10)
            assert isinstance(error_stats, list), "get_error_stats should return list"
            assert len(error_stats) == 0, "Should return empty list"
            
            return True
        
        result = asyncio.run(test_methods())
        print("[OK] Analytics with None db_service: OK (all methods return empty structures)")
        return result
        
    except Exception as e:
        print(f"[FAIL] Analytics with None db_service: FAILED")
        print(f"   Error: {e}")
        traceback.print_exc()
        return False


def test_analytics_with_mock_db() -> bool:
    """Test Analytics service with mock db_service that has get_connection."""
    try:
        from app.admin.analytics import Analytics
        
        # Create mock db_service that raises AttributeError on get_connection
        class MockDBService:
            def get_connection(self):
                raise AttributeError("get_connection not implemented")
        
        analytics = Analytics(MockDBService())
        
        # _check_db_service should return True (has get_connection method)
        # But get_connection will fail - should be caught in try/except
        import asyncio
        
        async def test_methods():
            # All methods should catch exceptions and return empty structures
            revenue_stats = await analytics.get_revenue_stats(period_days=30)
            assert isinstance(revenue_stats, dict), "Should return dict even on error"
            
            return True
        
        result = asyncio.run(test_methods())
        print("[OK] Analytics with mock db_service: OK (exceptions caught)")
        return result
        
    except Exception as e:
        print(f"[FAIL] Analytics with mock db_service: FAILED")
        print(f"   Error: {e}")
        traceback.print_exc()
        return False


def test_admin_handler_imports() -> bool:
    """Test that admin handlers can be imported without errors."""
    try:
        from bot.handlers.admin import router, set_services
        print("[OK] Admin handlers import: OK")
        return True
    except Exception as e:
        print(f"[FAIL] Admin handlers import: FAILED")
        print(f"   Error: {e}")
        traceback.print_exc()
        return False


def main():
    """Run all admin analytics smoke tests."""
    print("=" * 60)
    print("SMOKE TEST: Admin Analytics Fail-Open")
    print("=" * 60)
    print()
    
    all_passed = True
    
    all_passed &= test_admin_handler_imports()
    all_passed &= test_analytics_without_db()
    all_passed &= test_analytics_with_mock_db()
    
    print()
    print("=" * 60)
    if all_passed:
        print("[OK] ALL TESTS PASSED - Admin analytics is fail-open")
        print("=" * 60)
        return 0
    else:
        print("[FAIL] SOME TESTS FAILED - Fix admin analytics before deploy")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())

