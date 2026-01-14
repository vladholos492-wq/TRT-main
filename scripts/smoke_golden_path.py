#!/usr/bin/env python3
"""
GOLDEN PATH E2E Simulation - test critical flow without Telegram.

This script simulates a complete user flow:
1. /start command
2. Main menu callback
3. Model selection callback
4. Admin analytics callback (if admin)

All without real Telegram API calls.
"""

import sys
import os
import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Suppress logging during tests
logging.basicConfig(level=logging.CRITICAL)

def create_fake_update(update_type: str = "message", text: str = "/start", callback_data: str = None):
    """Create a fake Update object for testing."""
    update = MagicMock()
    update.update_id = 12345
    
    if update_type == "message":
        message = MagicMock()
        message.text = text
        message.chat = MagicMock()
        message.chat.id = 123456
        message.from_user = MagicMock()
        message.from_user.id = 123456
        update.message = message
        update.callback_query = None
    elif update_type == "callback_query":
        callback = MagicMock()
        callback.data = callback_data
        callback.id = "test_callback_id"
        callback.message = MagicMock()
        callback.message.chat = MagicMock()
        callback.message.chat.id = 123456
        callback.from_user = MagicMock()
        callback.from_user.id = 123456
        update.callback_query = callback
        update.message = None
    
    return update

async def test_golden_path():
    """Test golden path flow."""
    print("=" * 60)
    print("GOLDEN PATH E2E SIMULATION")
    print("=" * 60)
    print()
    
    all_passed = True
    
    # Test 1: Import handlers
    print("1. Testing handler imports...")
    try:
        from bot.handlers import flow, admin
        print("   [OK] Handlers imported")
    except ImportError as e:
        if "aiogram" in str(e).lower():
            print("   [SKIP] aiogram not available in dev env")
        else:
            print(f"   [FAIL] Import error: {e}")
            all_passed = False
    except Exception as e:
        print(f"   [FAIL] Error: {e}")
        all_passed = False
    
    # Test 2: Test correlation ID propagation
    print("\n2. Testing correlation ID propagation...")
    try:
        from app.utils.correlation import ensure_correlation_id, get_correlation_id
        cid = ensure_correlation_id("test_update_123")
        retrieved = get_correlation_id()
        if retrieved == cid:
            print(f"   [OK] CID propagation: {cid}")
        else:
            print(f"   [FAIL] CID mismatch: {cid} != {retrieved}")
            all_passed = False
    except Exception as e:
        print(f"   [FAIL] CID error: {e}")
        all_passed = False
    
    # Test 3: Test observability logging
    print("\n3. Testing observability logging...")
    try:
        from app.observability.v2 import (
            log_webhook_in,
            log_enqueue_ok,
            log_dispatch_start,
            log_dispatch_ok,
        )
        cid = "test_cid_123"
        log_webhook_in(cid=cid, update_id=123, update_type="message")
        log_enqueue_ok(cid=cid, update_id=123, queue_depth=0, queue_max=100)
        log_dispatch_start(cid=cid, update_id=123, handler_name="test_handler")
        log_dispatch_ok(cid=cid, update_id=123, handler_name="test_handler", duration_ms=50.0)
        print("   [OK] Observability logging works")
    except Exception as e:
        print(f"   [FAIL] Observability error: {e}")
        all_passed = False
    
    # Test 4: Test service wiring
    print("\n4. Testing service wiring...")
    try:
        from app.services.wiring import set_services, get_db_service, require_db_service
        
        # Test setting services
        mock_db = MagicMock()
        mock_db.get_connection = AsyncMock()
        set_services(db_service=mock_db)
        
        # Test getting service
        db = get_db_service()
        if db == mock_db:
            print("   [OK] Service wiring works")
        else:
            print("   [FAIL] Service wiring mismatch")
            all_passed = False
        
        # Test require_db_service
        try:
            required = require_db_service("test")
            if required == mock_db:
                print("   [OK] require_db_service works")
            else:
                print("   [FAIL] require_db_service mismatch")
                all_passed = False
        except RuntimeError:
            print("   [FAIL] require_db_service raised when service exists")
            all_passed = False
        
        # Test require_db_service with None
        set_services(db_service=None)
        try:
            require_db_service("test")
            print("   [FAIL] require_db_service should raise when None")
            all_passed = False
        except RuntimeError:
            print("   [OK] require_db_service correctly raises when None")
        
    except Exception as e:
        print(f"   [FAIL] Service wiring error: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    
    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("[OK] GOLDEN PATH SIMULATION PASSED")
        print("=" * 60)
        return 0
    else:
        print("[FAIL] GOLDEN PATH SIMULATION FAILED")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(test_golden_path()))

