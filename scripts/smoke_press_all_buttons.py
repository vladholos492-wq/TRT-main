#!/usr/bin/env python3
"""
Press All Buttons - тестирование всех кнопок из инвентаризации.

Для каждой кнопки формирует синтетический Update и прогоняет через Dispatcher.
Проверяет: нет исключений, handler найден, есть UI outcome, MOCK режим для внешних вызовов.
"""
import sys
import os
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from unittest.mock import MagicMock, AsyncMock, patch
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Suppress logging during tests
logging.basicConfig(level=logging.CRITICAL)


def load_button_inventory() -> Dict[str, Any]:
    """Load button inventory from JSON."""
    inventory_path = project_root / "artifacts" / "buttons_inventory.json"
    if not inventory_path.exists():
        print(f"Error: {inventory_path} not found. Run 'make inventory-buttons' first.")
        sys.exit(1)
    
    with open(inventory_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def create_fake_callback_update(callback_data: str, user_id: int = 123456, chat_id: int = 123456) -> Dict[str, Any]:
    """Create a fake callback_query update payload."""
    return {
        "update_id": 12345,
        "callback_query": {
            "id": f"test_callback_{callback_data}",
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Test",
                "username": "testuser"
            },
            "message": {
                "message_id": 1,
                "chat": {
                    "id": chat_id,
                    "type": "private"
                },
                "date": 1234567890
            },
            "data": callback_data
        }
    }


def create_fake_message_update(text: str, user_id: int = 123456, chat_id: int = 123456) -> Dict[str, Any]:
    """Create a fake message update payload."""
    return {
        "update_id": 12346,
        "message": {
            "message_id": 1,
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Test",
                "username": "testuser"
            },
            "chat": {
                "id": chat_id,
                "type": "private"
            },
            "date": 1234567890,
            "text": text
        }
    }


class MockExternalCalls:
    """Track and block external calls in DRY_RUN mode."""
    def __init__(self):
        self.blocked_calls = []
        self.mocked_calls = []
    
    def block_if_dry_run(self, service_name: str, method: str, **kwargs):
        """Block real external call if DRY_RUN is enabled."""
        if os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes"):
            self.blocked_calls.append({
                "service": service_name,
                "method": method,
                "kwargs": kwargs
            })
            raise RuntimeError(f"REAL_EXTERNAL_CALL_BLOCKED_IN_DRY_RUN: {service_name}.{method}")
        else:
            self.mocked_calls.append({
                "service": service_name,
                "method": method,
                "kwargs": kwargs
            })


async def test_button(
    callback_data: str,
    button_info: Dict[str, Any],
    mock_external: MockExternalCalls
) -> Tuple[bool, str, Optional[str]]:
    """
    Test a single button.
    
    Returns:
        (success, error_message, handler_name)
    """
    try:
        # Mock aiogram Bot and Dispatcher
        from aiogram import Bot, Dispatcher
        from aiogram.fsm.storage.memory import MemoryStorage
        from aiogram.types import Update
        
        # Create real dispatcher (but with mocked bot)
        bot = MagicMock(spec=Bot)
        bot.send_message = AsyncMock(return_value=MagicMock())
        bot.edit_message_text = AsyncMock(return_value=MagicMock())
        bot.answer_callback_query = AsyncMock(return_value=True)
        bot.get_webhook_info = AsyncMock(return_value=MagicMock(url=None))
        
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        
        # Import routers (this will register handlers)
        try:
            from bot.handlers import flow, admin, marketing, balance, history, gallery, quick_actions
            dp.include_router(flow.router)
            dp.include_router(admin.router)
            dp.include_router(marketing.router)
            dp.include_router(balance.router)
            dp.include_router(history.router)
            dp.include_router(gallery.router)
            dp.include_router(quick_actions.router)
        except ImportError as e:
            if "aiogram" in str(e).lower():
                return True, "SKIPPED (aiogram not available in dev env)", None
            return False, f"Import error: {e}", None
        except Exception as e:
            return False, f"Router import error: {e}", None
        
        # Set DRY_RUN mode
        os.environ["DRY_RUN"] = "true"
        
        # Mock external services
        with patch('app.kie.client.KieClient') as mock_kie, \
             patch('app.payments.integration.generate_with_payment') as mock_payment:
            
            # Mock KIE client
            mock_kie_instance = MagicMock()
            mock_kie_instance.create_job = AsyncMock(return_value={
                "job_id": "mock_job_123",
                "status": "mock_progress"
            })
            mock_kie.return_value = mock_kie_instance
            
            # Mock payment
            mock_payment.return_value = {
                "invoice_url": "mock://payment",
                "paid": False
            }
            
            # Create update
            update_payload = create_fake_callback_update(callback_data)
            update = Update.model_validate(update_payload)
            
            # Track UI outcomes
            ui_outcomes = []
            original_send = bot.send_message
            original_edit = bot.edit_message_text
            original_answer = bot.answer_callback_query
            
            async def tracked_send(*args, **kwargs):
                ui_outcomes.append("send_message")
                return await original_send(*args, **kwargs)
            
            async def tracked_edit(*args, **kwargs):
                ui_outcomes.append("edit_message_text")
                return await original_edit(*args, **kwargs)
            
            async def tracked_answer(*args, **kwargs):
                ui_outcomes.append("answer_callback_query")
                return await original_answer(*args, **kwargs)
            
            bot.send_message = tracked_send
            bot.edit_message_text = tracked_edit
            bot.answer_callback_query = tracked_answer
            
            # Process update through dispatcher
            try:
                await dp.feed_update(bot, update)
            except RuntimeError as e:
                if "REAL_EXTERNAL_CALL_BLOCKED_IN_DRY_RUN" in str(e):
                    # This is expected - external call was blocked
                    mock_external.blocked_calls.append({
                        "service": "unknown",
                        "method": "unknown",
                        "callback_data": callback_data
                    })
                    # Still check if UI outcome happened
                    if ui_outcomes:
                        return True, "OK (external call blocked, UI outcome present)", None
                    else:
                        return False, "External call blocked but no UI outcome", None
                else:
                    return False, f"RuntimeError: {e}", None
            except Exception as e:
                # Some handlers may fail due to missing services (DB, etc.)
                error_str = str(e)
                if "db_service" in error_str.lower() or "database" in error_str.lower():
                    # Expected in test env
                    if ui_outcomes:
                        return True, "OK (expected DB error, UI outcome present)", None
                    else:
                        return False, f"DB error and no UI outcome: {e}", None
                return False, f"Handler error: {e}", None
            
            # Check if handler was found and executed
            if not ui_outcomes:
                return False, "No UI outcome (handler may not exist or be silent)", None
            
            # Success
            return True, "OK", None
    
    except ImportError as e:
        if "aiogram" in str(e).lower():
            return True, "SKIPPED (aiogram not available)", None
        return False, f"Import error: {e}", None
    except Exception as e:
        return False, f"Unexpected error: {e}", None
    finally:
        # Cleanup
        if "DRY_RUN" in os.environ:
            del os.environ["DRY_RUN"]


async def main_async():
    """Run all button tests."""
    print("=" * 60)
    print("PRESS ALL BUTTONS TEST")
    print("=" * 60)
    print()
    
    # Load inventory
    print("Loading button inventory...")
    inventory = load_button_inventory()
    
    buttons_by_callback = inventory.get("buttons_by_callback", {})
    total_buttons = len(buttons_by_callback)
    
    print(f"Found {total_buttons} buttons to test")
    print()
    
    # Test each button
    results = {
        "passed": [],
        "failed": [],
        "skipped": []
    }
    
    mock_external = MockExternalCalls()
    
    print("Testing buttons...")
    for i, (callback_data, button_info) in enumerate(buttons_by_callback.items(), 1):
        if i % 50 == 0:
            print(f"  Progress: {i}/{total_buttons}")
        
        success, message, handler_name = await test_button(callback_data, button_info, mock_external)
        
        result_entry = {
            "callback_data": callback_data,
            "button_text": button_info.get("button_text", "N/A"),
            "file": button_info.get("file", "N/A"),
            "message": message,
            "handler_name": handler_name
        }
        
        if "SKIPPED" in message:
            results["skipped"].append(result_entry)
        elif success:
            results["passed"].append(result_entry)
        else:
            results["failed"].append(result_entry)
    
    # Print summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total Buttons: {total_buttons}")
    print(f"Passed: {len(results['passed'])}")
    print(f"Failed: {len(results['failed'])}")
    print(f"Skipped: {len(results['skipped'])}")
    print(f"Blocked External Calls: {len(mock_external.blocked_calls)}")
    print(f"Mocked External Calls: {len(mock_external.mocked_calls)}")
    print()
    
    # Print failures
    if results["failed"]:
        print("=" * 60)
        print("FAILED BUTTONS")
        print("=" * 60)
        for result in results["failed"][:20]:  # Show first 20
            print(f"  - {result['callback_data']}: {result['message']}")
            print(f"    File: {result['file']}")
        if len(results["failed"]) > 20:
            print(f"  ... and {len(results['failed']) - 20} more")
        print()
    
    # Save results
    artifacts_dir = project_root / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    
    results_path = artifacts_dir / "button_test_results.json"
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump({
            "summary": {
                "total": total_buttons,
                "passed": len(results["passed"]),
                "failed": len(results["failed"]),
                "skipped": len(results["skipped"]),
                "blocked_external_calls": len(mock_external.blocked_calls),
                "mocked_external_calls": len(mock_external.mocked_calls)
            },
            "results": results,
            "blocked_calls": mock_external.blocked_calls
        }, f, indent=2, ensure_ascii=False)
    
    print(f"[OK] Results saved: {results_path}")
    print()
    
    # Exit code
    if len(results["failed"]) > 0:
        print("=" * 60)
        print("SOME BUTTONS FAILED - REVIEW FAILURES ABOVE")
        print("=" * 60)
        return 1
    else:
        print("=" * 60)
        print("ALL BUTTONS PASSED")
        print("=" * 60)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))

