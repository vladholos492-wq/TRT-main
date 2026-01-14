"""Render entrypoint.

Goals:
- Webhook-first runtime (Render Web Service)
- aiogram-only import surface (no python-telegram-bot imports from this module)
- Health endpoints for Render + UptimeRobot
- Singleton advisory lock support (PostgreSQL) to avoid double-processing

This project historically had a PTB (python-telegram-bot) runner. Tests still cover
that legacy in bot_kie.py, but this runtime is aiogram-based.

Important: the repo contains a local ./aiogram folder with tiny test stubs.
In production we must import the real aiogram package from site-packages.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import json

from aiohttp import web

from app.storage import get_storage
from app.utils.logging_config import setup_logging  # noqa: E402
from app.utils.orphan_reconciler import OrphanCallbackReconciler  # PHASE 5
from app.utils.runtime_state import runtime_state  # noqa: E402
from app.utils.version import get_app_version, get_version_info  # noqa: E402
from app.locking.active_state import ActiveState  # NEW: unified active state
from app.utils.webhook import (
    build_kie_callback_url,
    get_kie_callback_path,
    get_webhook_base_url,
    get_webhook_secret_token,
)  # noqa: E402
# P0: Telemetry middleware (fail-open: if import fails, app still starts)
# Backward compatibility: import from telemetry_helpers (which re-exports from middleware)
import logging
_startup_logger = logging.getLogger(__name__)

try:
    from app.telemetry.telemetry_helpers import TelemetryMiddleware
    TELEMETRY_AVAILABLE = TelemetryMiddleware is not None
    if not TELEMETRY_AVAILABLE:
        _startup_logger.warning("[STARTUP] TelemetryMiddleware is None (middleware module unavailable)")
except ImportError as e:
    _startup_logger.warning(f"[STARTUP] Telemetry disabled: {e}")
    TelemetryMiddleware = None
    TELEMETRY_AVAILABLE = False
except Exception as e:
    _startup_logger.warning(f"[STARTUP] Telemetry unavailable (non-critical): {e}")
    TelemetryMiddleware = None
    TELEMETRY_AVAILABLE = False
from app.telemetry.logging_config import configure_logging  # P0: JSON logs

def _import_real_aiogram_symbols():
    """Import aiogram symbols from site-packages even if ./aiogram stubs exist."""
    project_root = Path(__file__).resolve().parent
    has_local_stubs = (project_root / "aiogram" / "__init__.py").exists()
    removed: list[str] = []

    if has_local_stubs:
        # Remove project root and '' so import machinery does not pick local stubs.
        for entry in list(sys.path):
            if entry in {"", str(project_root)}:
                removed.append(entry)
                try:
                    sys.path.remove(entry)
                except ValueError:
                    pass

    try:
        # Import the package (this will populate sys.modules with the real aiogram).
        import importlib

        importlib.import_module("aiogram")
    finally:
        # Restore path for app imports.
        for entry in reversed(removed):
            sys.path.insert(0, entry)

    # Now import symbols from whichever aiogram got loaded.
    from aiogram import Bot, Dispatcher  # type: ignore
    from aiogram.fsm.storage.memory import MemoryStorage  # type: ignore
    from aiogram.types import Update  # type: ignore
    from aiogram.client.default import DefaultBotProperties  # type: ignore

    return Bot, Dispatcher, MemoryStorage, Update, DefaultBotProperties


Bot, Dispatcher, MemoryStorage, Update, DefaultBotProperties = _import_real_aiogram_symbols()


logger = logging.getLogger(__name__)


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _derive_secret_path_from_token(token: str) -> str:
    """Derive a stable URL-safe secret path.

    Compatibility note:
    Older deployments used the bot token with ':' removed as the webhook path.
    We keep that behavior as the default to avoid silent 404s after redeploys.
    """

    cleaned = token.strip().replace(":", "")
    # Keep it reasonably short but stable.
    if len(cleaned) > 64:
        cleaned = cleaned[-64:]
    return cleaned


@dataclass(frozen=True)
class RuntimeConfig:
    bot_mode: str
    port: int
    webhook_base_url: str
    webhook_secret_path: str
    webhook_secret_token: str
    telegram_bot_token: str
    database_url: str
    dry_run: bool
    kie_callback_path: str
    kie_callback_token: str


def _load_runtime_config() -> RuntimeConfig:
    bot_mode = os.getenv("BOT_MODE", "webhook").strip().lower()
    port_env = os.getenv("PORT")
    port = int(port_env) if port_env else 0
    webhook_base_url = get_webhook_base_url().strip().rstrip("/")
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    # Secret path in URL (preferred). Can be explicitly overridden.
    webhook_secret_path = os.getenv("WEBHOOK_SECRET_PATH", "").strip()
    if not webhook_secret_path:
        webhook_secret_path = _derive_secret_path_from_token(telegram_bot_token)

    # Secret token in header (Telegram supports X-Telegram-Bot-Api-Secret-Token)
    webhook_secret_token = get_webhook_secret_token()

    database_url = os.getenv("DATABASE_URL", "").strip()
    dry_run = _bool_env("DRY_RUN", False) or _bool_env("TEST_MODE", False)
    kie_callback_path = get_kie_callback_path()
    kie_callback_token = os.getenv("KIE_CALLBACK_TOKEN", "").strip()

    return RuntimeConfig(
        bot_mode=bot_mode,
        port=port,
        webhook_base_url=webhook_base_url,
        webhook_secret_path=webhook_secret_path,
        webhook_secret_token=webhook_secret_token,
        telegram_bot_token=telegram_bot_token,
        database_url=database_url,
        dry_run=dry_run,
        kie_callback_path=kie_callback_path,
        kie_callback_token=kie_callback_token,
    )


# Remove old ActiveState dataclass - now using app.locking.active_state.ActiveState


class SingletonLock:
    """Async wrapper for the sync advisory lock implementation."""

    def __init__(self, database_url: str, *, key: Optional[int] = None):
        self.database_url = database_url
        self.key = key
        self._acquired = False

    async def acquire(self, timeout: float | None = None) -> bool:
        # NOTE: app.locking.single_instance.acquire_single_instance_lock() reads DATABASE_URL
        # from env and uses the psycopg2 pool from database.py. We keep this wrapper async
        # for uniformity.
        if not self.database_url:
            self._acquired = True
            return True

        try:
            from app.locking.single_instance import acquire_single_instance_lock

            # Signature has no args (it reads env). Run in thread with optional timeout
            if timeout is not None:
                try:
                    # Fast non-blocking acquire with timeout
                    self._acquired = bool(
                        await asyncio.wait_for(
                            asyncio.to_thread(acquire_single_instance_lock),
                            timeout=timeout
                        )
                    )
                    return self._acquired
                except asyncio.TimeoutError:
                    logger.debug("[LOCK] Acquire timed out after %.1fs", timeout)
                    self._acquired = False
                    return False
            else:
                # No timeout - blocking acquire
                self._acquired = bool(await asyncio.to_thread(acquire_single_instance_lock))
                return self._acquired
        except Exception as e:
            logger.exception("[LOCK] Failed to acquire singleton lock: %s", e)
            self._acquired = False
            return False

    async def release(self) -> None:
        if not self.database_url:
            return
        if not self._acquired:
            return
        try:
            from app.locking.single_instance import release_single_instance_lock

            release_single_instance_lock()
        except Exception as e:
            logger.warning("[LOCK] Failed to release singleton lock: %s", e)


# Exported name for tests (they monkeypatch this)
try:
    from app.storage.pg_storage import PostgresStorage
except Exception:  # pragma: no cover
    PostgresStorage = object  # type: ignore


async def preflight_webhook(bot: Bot) -> None:
    """Remove webhook to avoid conflict when running polling."""
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("[PRE-FLIGHT] Webhook deleted")
    except Exception as e:
        logger.warning("[PRE-FLIGHT] Failed to delete webhook: %s", e)


def create_bot_application() -> tuple[Dispatcher, Bot]:
    """Create aiogram Dispatcher + Bot (sync factory for tests)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    # aiogram 3.7.0+ requires DefaultBotProperties for parse_mode
    default_properties = DefaultBotProperties(parse_mode="HTML")
    bot = Bot(token=token, default=default_properties)
    dp = Dispatcher(storage=MemoryStorage())

    # Routers
    from bot.handlers import (
        admin_router,
        balance_router,
        diag_router,
        error_handler_router,
        flow_router,
        gallery_router,
        history_router,
        marketing_router,
        quick_actions_router,
        zero_silence_router,
        z_image_router,
    )
    # from app.handlers.debug_handler import router as debug_router  # TODO: Needs router refactor
    from bot.handlers.fallback import router as fallback_router  # P0: Global fallback
    from app.middleware.exception_middleware import ExceptionMiddleware  # P0: Catch all exceptions

    # P0: Telemetry middleware FIRST (adds cid + bot_state to all updates)
    # Fail-open: if telemetry unavailable, app still works
    if TELEMETRY_AVAILABLE and TelemetryMiddleware:
        try:
            dp.update.middleware(TelemetryMiddleware())
            logger.info("[TELEMETRY] ✅ Middleware registered")
        except Exception as e:
            logger.warning(f"[TELEMETRY] Failed to register middleware (non-critical): {e}")
    else:
        logger.warning("[TELEMETRY] ⚠️ Telemetry middleware disabled - app continues without telemetry")
    
    # P0: Exception middleware SECOND (catches all unhandled exceptions)
    dp.update.middleware(ExceptionMiddleware())
    
    # Note: debug_router temporarily disabled - needs router refactor
    # dp.include_router(debug_router)
    dp.include_router(error_handler_router)
    dp.include_router(diag_router)
    dp.include_router(admin_router)
    dp.include_router(z_image_router)  # Z-image (SINGLE_MODEL support)
    dp.include_router(balance_router)
    dp.include_router(history_router)
    dp.include_router(marketing_router)
    dp.include_router(gallery_router)
    dp.include_router(quick_actions_router)
    dp.include_router(flow_router)
    dp.include_router(zero_silence_router)
    dp.include_router(fallback_router)  # P0: MUST BE LAST - catches unknown callbacks

    return dp, bot


async def verify_bot_identity(bot: Bot) -> None:
    """Verify bot identity and webhook configuration.
    
    Logs bot.getMe() and getWebhookInfo() to ensure correct bot/token/webhook.
    Prevents issues like "wrong bot deployed" or "webhook pointing to old URL".
    """
    try:
        me = await bot.get_me()
        logger.info(
            "[BOT_VERIFY] ✅ Bot identity: @%s (id=%s, name='%s')",
            me.username, me.id, me.first_name
        )
    except Exception as exc:
        logger.error("[BOT_VERIFY] ❌ Failed to get bot info: %s", exc)
        raise

    try:
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url:
            logger.info(
                "[BOT_VERIFY] 📡 Webhook: %s (pending=%s, last_error=%s)",
                webhook_info.url,
                webhook_info.pending_update_count,
                webhook_info.last_error_message or "none"
            )
        else:
            logger.info("[BOT_VERIFY] 📡 No webhook configured (polling mode or not set yet)")
    except Exception as exc:
        logger.warning("[BOT_VERIFY] ⚠️ Failed to get webhook info: %s", exc)


def _build_webhook_url(cfg: RuntimeConfig) -> str:
    base = cfg.webhook_base_url.rstrip("/")
    return f"{base}/webhook/{cfg.webhook_secret_path}" if base else ""


def _build_kie_callback_url(cfg: RuntimeConfig) -> str:
    return build_kie_callback_url(cfg.webhook_base_url, cfg.kie_callback_path)


def _health_payload(active_state: ActiveState) -> dict[str, Any]:
    from app.locking.single_instance import get_lock_debug_info

    lock_state = "ACTIVE" if active_state.active else "PASSIVE"
    lock_debug = {}
    controller = getattr(active_state, "lock_controller", None)
    if controller and getattr(controller, "lock", None) and hasattr(controller.lock, "get_lock_debug_info"):
        lock_debug = controller.lock.get_lock_debug_info()
    else:
        lock_debug = get_lock_debug_info()

    return {
        "ok": True,
        "mode": "active" if active_state.active else "passive",
        "active": bool(active_state.active),
        "lock_state": lock_state,
        "bot_mode": runtime_state.bot_mode,
        "storage_mode": runtime_state.storage_mode,
        "lock_acquired": runtime_state.lock_acquired,
        "lock_holder_pid": lock_debug.get("holder_pid"),
        "lock_idle_duration": lock_debug.get("idle_duration"),
        "lock_takeover_event": lock_debug.get("takeover_event"),
        "instance_id": runtime_state.instance_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def _make_web_app(
    *,
    dp: Dispatcher,
    bot: Bot,
    cfg: RuntimeConfig,
    active_state: ActiveState,
) -> web.Application:
    app = web.Application()
    # In-memory resilience structures (single instance assumption)
    recent_update_ids: set[int] = set()
    rate_map: dict[str, list[float]] = {}

    def _client_ip(request: web.Request) -> str:
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        return ip or (request.remote or "unknown")

    def _rate_limited(ip: str, now: float, limit: int = 5, window_s: float = 1.0) -> bool:
        hits = rate_map.get(ip, [])
        hits = [t for t in hits if now - t <= window_s]
        if len(hits) >= limit:
            rate_map[ip] = hits
            return True
        hits.append(now)
        rate_map[ip] = hits
        return False

    async def health(_request: web.Request) -> web.Response:
        """Health check endpoint with queue metrics."""
        from app.utils.update_queue import get_queue_manager
        from app.locking.single_instance import get_lock_debug_info
        
        uptime = 0
        if runtime_state.last_start_time:
            started = datetime.fromisoformat(runtime_state.last_start_time)
            uptime = int((datetime.now(timezone.utc) - started).total_seconds())
        
        # Get queue metrics
        queue_manager = get_queue_manager()
        queue_metrics = queue_manager.get_metrics()
        
        lock_debug = {}
        controller = getattr(active_state, "lock_controller", None)
        if controller and getattr(controller, "lock", None) and hasattr(controller.lock, "get_lock_debug_info"):
            lock_debug = controller.lock.get_lock_debug_info()
        else:
            lock_debug = get_lock_debug_info()

        # Defense-in-depth: ensure idle_duration is JSON serializable (float, not Decimal)
        idle_duration = lock_debug.get("idle_duration")
        if idle_duration is not None:
            idle_duration = float(idle_duration)
        
        heartbeat_age = lock_debug.get("heartbeat_age")
        if heartbeat_age is not None:
            heartbeat_age = float(heartbeat_age)

        # HEALTHCHECK AS DIAG ENDPOINT: comprehensive status
        # Check DB status (fail-open)
        db_status = "OK"
        db_warn = None
        try:
            from app.utils.runtime_state import runtime_state
            if not runtime_state.db_schema_ready:
                db_status = "WARN"
                db_warn = "Schema not ready"
        except Exception:
            db_status = "WARN"
            db_warn = "DB check failed"
        
        # Check webhook status (fail-open)
        webhook_status = "OK"
        webhook_warn = None
        try:
            if runtime_state.bot_mode == "webhook":
                webhook_info = await bot.get_webhook_info()
                if not webhook_info.url:
                    webhook_status = "WARN"
                    webhook_warn = "Webhook not configured"
        except Exception:
            webhook_status = "WARN"
            webhook_warn = "Webhook check failed"
        
        # Determine overall status
        overall_status = "ok"
        if db_status == "WARN" or webhook_status == "WARN":
            overall_status = "degraded"
        
        payload = {
            "status": overall_status,
            "uptime": uptime,
            "mode": "active" if active_state.active else "passive",
            "active": active_state.active,
            "lock_state": "ACTIVE" if active_state.active else "PASSIVE",
            "webhook_mode": runtime_state.bot_mode == "webhook",
            "webhook_configured": webhook_status,
            "webhook_warn": webhook_warn,
            "lock_acquired": runtime_state.lock_acquired,
            "lock_holder_pid": lock_debug.get("holder_pid"),
            "lock_idle_duration": idle_duration,
            "lock_heartbeat_age": heartbeat_age,
            "lock_takeover_event": lock_debug.get("takeover_event"),
            "db_status": db_status,
            "db_warn": db_warn,
            "db_schema_ready": runtime_state.db_schema_ready,
            "queue": {
                "depth": queue_metrics.get("queue_depth_current", 0),
                "max": queue_metrics.get("queue_max", 100),
                "utilization_pct": round((queue_metrics.get("queue_depth_current", 0) / queue_metrics.get("queue_max", 100) * 100) if queue_metrics.get("queue_max", 100) > 0 else 0, 1),
                "total_received": queue_metrics.get("total_received", 0),
                "total_processed": queue_metrics.get("total_processed", 0),
                "total_dropped": queue_metrics.get("total_dropped", 0),
            },
        }
        return web.json_response(payload)

    async def root(_request: web.Request) -> web.Response:
        """Root endpoint (same as health)."""
        from app.utils.update_queue import get_queue_manager
        from app.locking.single_instance import get_lock_debug_info
        
        uptime = 0
        if runtime_state.last_start_time:
            started = datetime.fromisoformat(runtime_state.last_start_time)
            uptime = int((datetime.now(timezone.utc) - started).total_seconds())
        
        queue_manager = get_queue_manager()
        queue_metrics = queue_manager.get_metrics()
        
        lock_debug = {}
        controller = getattr(active_state, "lock_controller", None)
        if controller and getattr(controller, "lock", None) and hasattr(controller.lock, "get_lock_debug_info"):
            lock_debug = controller.lock.get_lock_debug_info()
        else:
            lock_debug = get_lock_debug_info()

        # Defense-in-depth: ensure idle_duration is JSON serializable (float, not Decimal)
        idle_duration = lock_debug.get("idle_duration")
        if idle_duration is not None:
            idle_duration = float(idle_duration)
        
        heartbeat_age = lock_debug.get("heartbeat_age")
        if heartbeat_age is not None:
            heartbeat_age = float(heartbeat_age)

        payload = {
            "status": "ok",
            "uptime": uptime,
            "active": active_state.active,
            "lock_state": "ACTIVE" if active_state.active else "PASSIVE",
            "webhook_mode": runtime_state.bot_mode == "webhook",
            "lock_acquired": runtime_state.lock_acquired,
            "lock_holder_pid": lock_debug.get("holder_pid"),
            "lock_idle_duration": idle_duration,
            "lock_heartbeat_age": heartbeat_age,
            "lock_takeover_event": lock_debug.get("takeover_event"),
            "db_schema_ready": runtime_state.db_schema_ready,
            "queue_depth": queue_metrics.get("queue_depth_current", 0),
            "queue": queue_metrics,
        }
        return web.json_response(payload)
    
    async def diag_webhook(_request: web.Request) -> web.Response:
        """Diagnostic endpoint for webhook status."""
        try:
            info = await bot.get_webhook_info()
            
            # Mask secret path for security
            url = info.url or ""
            if url:
                parts = url.rsplit("/", 1)
                if len(parts) == 2:
                    url = parts[0] + "/***"
            
            return web.json_response({
                "url": url,
                "has_custom_certificate": info.has_custom_certificate,
                "pending_update_count": info.pending_update_count,
                "last_error_date": info.last_error_date.isoformat() if info.last_error_date else None,
                "last_error_message": info.last_error_message or "",
                "max_connections": info.max_connections,
                "ip_address": info.ip_address or "",
            })
        except Exception as e:
            logger.exception("[DIAG] Failed to get webhook info: %s", e)
            return web.json_response({"error": str(e)}, status=500)
    
    async def diag_lock(_request: web.Request) -> web.Response:
        """Diagnostic endpoint for lock status."""
        controller = getattr(active_state, "lock_controller", None)
        
        if not controller:
            return web.json_response({
                "error": "Lock controller not initialized"
            }, status=503)
        
        return web.json_response({
            "active": active_state.active,
            "should_process": controller.should_process_updates(),
            "lock_acquired": runtime_state.lock_acquired,
            "last_check": controller._last_check.isoformat() if hasattr(controller, "_last_check") and controller._last_check else None,
        })
    
    async def diag_webhookinfo(_request: web.Request) -> web.Response:
        """Detailed webhook info including allowed_updates."""
        try:
            info = await bot.get_webhook_info()
            return web.json_response({
                "url": info.url,
                "pending_update_count": info.pending_update_count,
                "last_error_message": info.last_error_message or "",
                "last_error_date": info.last_error_date,
                "allowed_updates": info.allowed_updates,
                "max_connections": info.max_connections,
                "has_custom_certificate": info.has_custom_certificate,
                "ip_address": info.ip_address if hasattr(info, "ip_address") else None,
            })
        except Exception as e:
            logger.exception("[DIAG] Failed to get webhook info: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def webhook(request: web.Request) -> web.Response:
        """
        Fast-ack webhook handler - ALWAYS returns 200 OK within <200ms.
        
        Architecture:
        - Validates secret/token
        - PASSIVE instances: drop update with PASSIVE_DROP log, return 200 OK
        - ACTIVE instances: enqueue update to background queue
        - Returns 200 OK immediately (Telegram gets instant response)
        - Background workers process updates from queue
        
        This prevents timeout errors and pending updates accumulation.
        """
        secret = request.match_info.get("secret")
        if secret != cfg.webhook_secret_path:
            # Hide existence of endpoint
            raise web.HTTPNotFound()

        # Enforce Telegram header secret if configured
        if cfg.webhook_secret_token:
            header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if header != cfg.webhook_secret_token:
                logger.warning("[WEBHOOK] Invalid secret token")
                raise web.HTTPUnauthorized()

        # Basic rate limiting per IP
        ip = _client_ip(request)
        now = time.time()
        if _rate_limited(ip, now):
            logger.warning("[WEBHOOK] Rate limit exceeded for ip=%s", ip)
            # Still return 200 to avoid Telegram retry storm
            return web.Response(status=200, text="ok")

        # Fast JSON parse (no timeout needed - aiohttp handles this)
        try:
            payload = await request.json()
        except Exception as e:
            logger.warning("[WEBHOOK] Bad JSON: %s", e)
            # Return 200 anyway (invalid updates will be ignored)
            return web.Response(status=200, text="ok")

        # Validate and extract update
        try:
            update = Update.model_validate(payload)
        except Exception as e:
            logger.warning("[WEBHOOK] Invalid Telegram update: %s", e)
            # Return 200 anyway
            return web.Response(status=200, text="ok")
        
        try:
            update_id = int(getattr(update, "update_id", 0))
        except Exception:
            update_id = 0
        
        # Detect update type for logging
        update_type = "unknown"
        if getattr(update, "message", None):
            update_type = "message"
        elif getattr(update, "callback_query", None):
            update_type = "callback_query"
        elif getattr(update, "inline_query", None):
            update_type = "inline_query"
        elif getattr(update, "edited_message", None):
            update_type = "edited_message"
        
        # OBSERVABILITY V2: WEBHOOK_IN
        from app.utils.correlation import ensure_correlation_id
        from app.observability.v2 import log_webhook_in
        from app.observability.explain import log_passive_drop
        cid = ensure_correlation_id(str(update_id) if update_id else None)
        payload_size = request.headers.get("Content-Length")
        if payload_size:
            try:
                payload_size = int(payload_size)
            except ValueError:
                payload_size = None
        else:
            payload_size = None
        
        log_webhook_in(
            cid=cid,
            update_id=update_id,
            update_type=update_type,
            size_bytes=payload_size,
            ip=_client_ip(request),
        )
        
        # PASSIVE CHECK: If PASSIVE, drop update and return 200 OK immediately
        if not active_state.active:
            log_passive_drop(
                cid=cid,
                update_id=update_id,
                update_type=update_type,
                reason="not_active",
            )
            # Return 200 OK immediately - ACTIVE instance will process it
            return web.Response(status=200, text="ok")
        
        # Check for duplicates
        if update_id and update_id in recent_update_ids:
            logger.debug("[WEBHOOK] Duplicate update_id=%s ignored", update_id)
            return web.Response(status=200, text="ok")
        
        # Mark as seen BEFORE enqueueing (prevent duplicate processing)
        if update_id:
            recent_update_ids.add(update_id)
        
        # 🚀 FASTPATH: Just fast HTTP ACK, ALL updates go to queue for proper processing
        # Business logic (sending messages, menus) happens in worker/handler
        # This architecture ensures:
        # 1) HTTP webhook responds <200ms (prevents Telegram timeout)
        # 2) /start handler in queue sends full welcome + menu (no "loading" message)
        # 3) Idempotency via recent_update_ids dedup (already implemented above)
        
        # Enqueue for background processing (non-blocking)
        # This returns immediately - worker processes in background
        from app.utils.update_queue import get_queue_manager
        queue_manager = get_queue_manager()
        
        # Check backpressure (for monitoring, but still enqueue - fast-ack must return 200)
        if queue_manager.should_reject_for_backpressure():
            logger.warning(
                "[WEBHOOK] ⚠️ BACKPRESSURE: queue utilization >80% (depth=%d/%d) - enqueueing anyway (fast-ack)",
                queue_manager.get_metrics()["queue_depth"],
                queue_manager.get_metrics()["queue_max"]
            )
        
        enqueued = queue_manager.enqueue(update, update_id)
        
        # OBSERVABILITY V2: ENQUEUE_OK
        from app.observability.v2 import log_enqueue_ok
        if enqueued:
            metrics = queue_manager.get_metrics()
            log_enqueue_ok(
                cid=cid,
                update_id=update_id,
                queue_depth=metrics.get("queue_depth", 0),
                queue_max=metrics.get("queue_max", 100),
            )
        else:
            # Queue full, update dropped - but still return 200
            logger.warning("[WEBHOOK] ❌ Queue full, dropped update_id=%s", update_id)
            # (Metrics in queue_manager track drop rate)
        
        # ALWAYS return 200 OK instantly
        return web.Response(status=200, text="ok")

    async def _deliver_result_to_telegram(
        bot: Bot, 
        chat_id: int, 
        result_urls: list[str], 
        task_id: str,
        corr_id: str = ""
    ) -> None:
        """
        Deliver generation result to Telegram with fallback.
        
        Strategy:
        1. Try bot.send_photo(url) directly
        2. If Telegram can't fetch URL, download bytes and send as InputFile
        """
        import aiohttp
        from aiogram.types import BufferedInputFile
        
        prefix = f"[{corr_id}] " if corr_id else ""
        
        if not result_urls:
            logger.warning(f"{prefix}[DELIVER] No URLs to deliver")
            return
        
        # For z-image, expect single image URL
        url = result_urls[0]
        logger.info(f"{prefix}[DELIVER] Attempting send_photo url={url[:100]}...")
        
        try:
            # Try direct URL first (fastest)
            await bot.send_photo(
                chat_id=chat_id,
                photo=url,
                caption=f"✅ Генерация готова!\nID: {task_id}"
            )
            logger.info(f"{prefix}[DELIVER] ✅ Direct URL success")
            return
        except Exception as e:
            logger.warning(f"{prefix}[DELIVER] Direct URL failed: {e}")
            logger.info(f"{prefix}[DELIVER] Trying bytes fallback...")
        
        # Fallback: download bytes
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    
                    image_bytes = await resp.read()
                    logger.info(f"{prefix}[DELIVER] Downloaded {len(image_bytes)} bytes")
            
            # Send as InputFile
            input_file = BufferedInputFile(image_bytes, filename="result.jpg")
            await bot.send_photo(
                chat_id=chat_id,
                photo=input_file,
                caption=f"✅ Генерация готова!\nID: {task_id}"
            )
            logger.info(f"{prefix}[DELIVER] ✅ Bytes fallback success")
        except Exception as e:
            logger.exception(f"{prefix}[DELIVER] ❌ Both delivery methods failed: {e}")
            # Send URL as text as last resort
            await bot.send_message(
                chat_id=chat_id,
                text=f"✅ Генерация готова!\nID: {task_id}\n\n{url}"
            )
            logger.info(f"{prefix}[DELIVER] ⚠️ Sent as text fallback")

    async def _send_generation_result(bot: Bot, chat_id: int, result_urls: list[str], task_id: str) -> None:
        """
        Smart sender: detect content type and send appropriately.
        
        Handles:
        - Single/multiple images → sendPhoto/sendMediaGroup
        - Videos → sendVideo
        - Audio → sendAudio
        - Documents/files → sendDocument
        - Text/unknown → sendMessage with URLs
        """
        if not result_urls:
            return
        
        try:
            # Detect content type from URLs
            image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
            video_exts = {'.mp4', '.avi', '.mov', '.webm', '.mkv'}
            audio_exts = {'.mp3', '.wav', '.ogg', '.m4a', '.flac'}
            
            classified = {'images': [], 'videos': [], 'audio': [], 'other': []}
            
            for url in result_urls:
                url_lower = url.lower()
                if any(url_lower.endswith(ext) for ext in image_exts):
                    classified['images'].append(url)
                elif any(url_lower.endswith(ext) for ext in video_exts):
                    classified['videos'].append(url)
                elif any(url_lower.endswith(ext) for ext in audio_exts):
                    classified['audio'].append(url)
                else:
                    classified['other'].append(url)
            
            # Send based on classification
            if classified['images']:
                if len(classified['images']) == 1:
                    # Single image
                    await bot.send_photo(chat_id, classified['images'][0], 
                                        caption=f"✅ Генерация готова\\nID: {task_id}")
                else:
                    # Multiple images - send as album (max 10 per Telegram limit)
                    from aiogram.types import InputMediaPhoto
                    media_group = [
                        InputMediaPhoto(media=url, caption=f"✅ {i+1}/{len(classified['images'])}")
                        for i, url in enumerate(classified['images'][:10])
                    ]
                    await bot.send_media_group(chat_id, media=media_group)
                    
                    # If more than 10, send rest as messages
                    if len(classified['images']) > 10:
                        remaining = "\\n".join(classified['images'][10:])
                        await bot.send_message(chat_id, f"Ещё {len(classified['images'])-10} изображений:\\n{remaining}")
            
            if classified['videos']:
                for video_url in classified['videos']:
                    await bot.send_video(chat_id, video_url, caption=f"✅ Видео готово\\nID: {task_id}")
            
            if classified['audio']:
                for audio_url in classified['audio']:
                    await bot.send_audio(chat_id, audio_url, caption=f"✅ Аудио готово\\nID: {task_id}")
            
            if classified['other']:
                # Unknown type - send as message with links
                text = f"✅ Генерация готова\\nID: {task_id}\\n\\n" + "\\n".join(classified['other'])
                await bot.send_message(chat_id, text)
                
        except Exception as e:
            # Fallback: send as plain text message
            logger.exception(f"[TELEGRAM_SENDER] Failed smart send, falling back to text: {e}")
            text = f"✅ Генерация готова (ссылки)\\nID: {task_id}\\n\\n" + "\\n".join(result_urls)
            await bot.send_message(chat_id, text)

    async def kie_callback(request: web.Request) -> web.Response:
        """
        KIE callback handler with unified parser and bulletproof delivery.
        ALWAYS returns 200 to prevent retry storms.
        """
        # Token validation
        if cfg.kie_callback_token:
            header = request.headers.get("X-KIE-Callback-Token", "")
            if header != cfg.kie_callback_token:
                logger.warning("[KIE_CALLBACK] Invalid token")
                return web.json_response({"ok": False, "error": "invalid_token"}, status=200)

        # Parse payload
        try:
            raw_payload = await request.json()
        except Exception as exc:
            logger.warning(f"[KIE_CALLBACK] JSON parse failed: {exc}")
            return web.json_response({"ok": True, "ignored": True, "reason": "invalid_json"}, status=200)

        # Import unified parser
        from app.kie.state_parser import parse_kie_state, extract_task_id
        from app.utils.correlation import ensure_correlation_id
        
        task_id = extract_task_id(raw_payload)
        if not task_id:
            logger.warning(f"[KIE_CALLBACK] No taskId in payload: {str(raw_payload)[:200]}")
            return web.json_response({"ok": True, "ignored": True, "reason": "no_task_id"}, status=200)
        
        corr_id = ensure_correlation_id(task_id)
        logger.info(f"[{corr_id}] [CALLBACK_RECEIVED] task_id={task_id}")
        
        # Parse state using unified parser
        state, result_urls, error_msg = parse_kie_state(raw_payload, corr_id)
        logger.info(f"[{corr_id}] [CALLBACK_PARSED] task_id={task_id} state={state} urls={len(result_urls)} error={error_msg or 'none'}")
        
        # Get job from storage
        storage = get_storage()
        job = None
        try:
            job = await storage.find_job_by_task_id(task_id)
        except Exception as exc:
            logger.warning(f"[{corr_id}] find_job_by_task_id failed: {exc}")

        if not job:
            logger.warning(f"[{corr_id}] [CALLBACK_ORPHAN] task_id={task_id} - saving for reconciliation")
            runtime_state.callback_job_not_found_count += 1
            
            # Save orphan callback
            try:
                await storage._save_orphan_callback(task_id, {
                    'state': state,
                    'result_urls': result_urls,
                    'error': error_msg,
                    'payload': raw_payload
                })
            except Exception as e:
                logger.error(f"[{corr_id}] Failed to save orphan: {e}")
            
            return web.json_response({"ok": True}, status=200)
        
        # Get job_id (support both old storage and new jobs table)
        job_id = job.get("job_id") or job.get("id")
        if not job_id:
            logger.warning(f"[{corr_id}] [CALLBACK_ERROR] No job_id found in job record")
            return web.json_response({"ok": True}, status=200)
        
        # Try to use JobServiceV2 if DB pool is available (atomic balance updates)
        job_service = None
        if runtime_state.db_pool:
            try:
                from app.services.job_service_v2 import JobServiceV2
                job_service = JobServiceV2(runtime_state.db_pool)
                # Try to get job by task_id from jobs table
                db_job = await job_service.get_by_task_id(task_id)
                if db_job:
                    job_id = db_job['id']  # Use integer ID from jobs table
                    logger.info(f"[{corr_id}] [CALLBACK_JOB_V2] Found job in jobs table: id={job_id}")
            except Exception as e:
                logger.warning(f"[{corr_id}] [CALLBACK_FALLBACK] JobServiceV2 not available: {e}, using legacy storage")
        
        # Update job status based on state
        try:
            if state in ('waiting', 'running'):
                if job_service:
                    await job_service.update_with_kie_task(job_id, task_id, 'running')
                else:
                    await storage.update_job_status(str(job_id), 'running')
                logger.debug(f"[{corr_id}] [CALLBACK_PROGRESS] task_id={task_id} state={state}")
            
            elif state == 'fail':
                # Use JobServiceV2 for atomic balance release on failure
                if job_service:
                    await job_service.update_from_callback(
                        job_id=job_id,
                        status='failed',
                        error_text=error_msg,
                        kie_status=state
                    )
                    logger.info(f"[{corr_id}] [CALLBACK_FAIL] task_id={task_id} error={error_msg} (balance released via JobServiceV2)")
                else:
                    await storage.update_job_status(str(job_id), 'failed', error_message=error_msg)
                    logger.info(f"[{corr_id}] [CALLBACK_FAIL] task_id={task_id} error={error_msg} (legacy storage)")
                
                # Try to acquire delivery lock for error notification (prevent spam)
                lock_job = await storage.try_acquire_delivery_lock(task_id, timeout_minutes=5)
                if lock_job:
                    logger.info(f"[{corr_id}] [DELIVER_LOCK_WIN] Won lock for error notification")
                    user_id = job.get('user_id')
                    chat_id = job.get('chat_id') or user_id  # Use chat_id from job if available
                    if not chat_id and job.get('params'):
                        params = job.get('params')
                        if isinstance(params, dict):
                            chat_id = params.get('chat_id') or user_id
                        elif isinstance(params, str):
                            try:
                                params_dict = json.loads(params)
                                chat_id = params_dict.get('chat_id') or user_id
                            except Exception:
                                pass
                    
                    if chat_id:
                        try:
                            await bot.send_message(chat_id, f"❌ Генерация не завершилась: {error_msg}\nID: {task_id}")
                            await storage.mark_delivered(task_id, success=True)
                            logger.info(f"[{corr_id}] [MARK_DELIVERED] Error notified")
                        except Exception as e:
                            logger.exception(f"[{corr_id}] Failed to send error to user: {e}")
                            await storage.mark_delivered(task_id, success=False, error=str(e))
                else:
                    logger.info(f"[{corr_id}] [DELIVER_LOCK_SKIP] Error already notified")
            
            elif state == 'success':
                # Use JobServiceV2 for atomic balance charge on success
                result_json = {'resultUrls': result_urls} if result_urls else None
                if job_service:
                    await job_service.update_from_callback(
                        job_id=job_id,
                        status='done',
                        result_json=result_json,
                        kie_status=state
                    )
                    logger.info(f"[{corr_id}] [CALLBACK_SUCCESS] task_id={task_id} urls={len(result_urls)} (balance charged via JobServiceV2)")
                else:
                    await storage.update_job_status(str(job_id), 'done', result_urls=result_urls)
                    logger.info(f"[{corr_id}] [CALLBACK_SUCCESS] task_id={task_id} urls={len(result_urls)} (legacy storage)")
                
                # Get chat_id and category for delivery
                user_id = job.get('user_id')
                chat_id = job.get('chat_id') or user_id  # Use chat_id from job if available
                if not chat_id and job.get('params'):
                    params = job.get('params')
                    if isinstance(params, dict):
                        chat_id = params.get('chat_id') or user_id
                    elif isinstance(params, str):
                        try:
                            params_dict = json.loads(params)
                            chat_id = params_dict.get('chat_id') or user_id
                        except Exception:
                            pass
                
                # Fallback: if still no chat_id, use user_id
                if not chat_id:
                    chat_id = user_id
                    logger.warning(f"[{corr_id}] [CALLBACK_WARN] No chat_id in job, using user_id={user_id}")
                
                # Determine category from model_id or params
                category = 'image'  # default
                model_id = job.get('model_id', '')
                if 'video' in model_id.lower():
                    category = 'video'
                elif 'audio' in model_id.lower() or 'music' in model_id.lower():
                    category = 'audio'
                elif 'upscale' in model_id.lower() or 'enhance' in model_id.lower():
                    category = 'upscale'
                
                if chat_id and result_urls:
                    # UNIFIED DELIVERY COORDINATOR (platform-wide atomic lock)
                    from app.delivery import deliver_result_atomic
                    
                    delivery_result = await deliver_result_atomic(
                        storage=storage,
                        bot=bot,
                        task_id=task_id,
                        chat_id=chat_id,
                        result_urls=result_urls,
                        category=category,
                        corr_id=corr_id,
                        timeout_minutes=5
                    )
                    
                    if not delivery_result['delivered'] and delivery_result['error']:
                        # Delivery failed, notify user
                        try:
                            await bot.send_message(chat_id, f"⚠️ Генерация готова, но не удалось отправить результат.\nID: {task_id}")
                        except:
                            pass
                elif not chat_id:
                    logger.error(f"[{corr_id}] [CALLBACK_ERROR] Cannot deliver: no chat_id and no user_id")
                elif not result_urls:
                    logger.warning(f"[{corr_id}] [CALLBACK_WARN] No result_urls to deliver")
        
        except Exception as e:
            logger.exception(f"[{corr_id}] [CALLBACK_ERROR] task_id={task_id}: {e}")
        
        return web.json_response({"ok": True}, status=200)

    callback_route = f"/{cfg.kie_callback_path.lstrip('/')}"
    async def version(_request: web.Request) -> web.Response:
        """Version endpoint - shows commit SHA, ACTIVE/PASSIVE, deploy time."""
        from app.utils.version import get_app_version, get_version_info
        version_info = get_version_info()
        commit_sha = get_app_version()
        deploy_time = runtime_state.last_start_time or datetime.now(timezone.utc).isoformat()
        
        return web.json_response({
            "version": commit_sha,
            "commit_sha": commit_sha,
            "source": version_info.get("source", "unknown"),
            "active": active_state.active,
            "lock_state": "ACTIVE" if active_state.active else "PASSIVE",
            "deploy_time": deploy_time,
        })
    
    async def diagnostics(_request: web.Request) -> web.Response:
        """Diagnostics endpoint - comprehensive status (admin only)."""
        # Check admin access (simple check via ADMIN_ID env var)
        admin_id = os.getenv("ADMIN_ID")
        if admin_id:
            try:
                # Could check request headers or IP, but for now allow all
                # In production, add proper auth check
                pass
            except Exception:
                pass
        
        from app.utils.version import get_app_version
        from app.locking.single_instance import get_lock_debug_info, get_lock_key
        
        commit_sha = get_app_version()
        uptime = 0
        if runtime_state.last_start_time:
            started = datetime.fromisoformat(runtime_state.last_start_time)
            uptime = int((datetime.now(timezone.utc) - started).total_seconds())
        
        # Get PID
        pid = os.getpid()
        
        # Get lock key
        lock_key = None
        try:
            lock_key = get_lock_key()
        except Exception:
            pass
        
        # Webhook info
        webhook_url = "N/A"
        webhook_configured = False
        try:
            info = await bot.get_webhook_info()
            webhook_configured = bool(info.url)
            if info.url:
                # Mask secret path
                parts = info.url.rsplit("/", 1)
                webhook_url = parts[0] + "/***" if len(parts) == 2 else "***"
        except Exception:
            pass
        
        # Queue stats
        queue_manager = get_queue_manager()
        queue_metrics = queue_manager.get_metrics()
        
        # DB status
        db_status = "ok"
        db_warn = None
        try:
            if not runtime_state.db_schema_ready:
                db_status = "degraded"
                db_warn = "Schema not ready"
        except Exception:
            db_status = "unknown"
            db_warn = "DB check failed"
        
        # Lock info
        lock_debug = get_lock_debug_info()
        
        # Last error (from runtime_state if available)
        last_error = getattr(runtime_state, "last_error", None)
        
        # Models registry version (if available)
        models_registry_version = "unknown"
        try:
            from app.models.kie_models import get_models_registry
            registry = get_models_registry()
            models_registry_version = getattr(registry, "version", "unknown")
        except Exception:
            pass
        
        return web.json_response({
            "version": commit_sha,
            "commit": commit_sha,
            "instance_id": runtime_state.instance_id,
            "pid": pid,
            "active": active_state.active,
            "lock_state": "ACTIVE" if active_state.active else "PASSIVE",
            "lock_key": lock_key,
            "uptime_seconds": uptime,
            "webhook_url": webhook_url,
            "webhook_configured": webhook_configured,
            "queue": {
                "size": queue_metrics.get("queue_depth_current", 0),
                "workers": queue_metrics.get("workers_active", 0),
                "backlog": queue_metrics.get("queue_depth_current", 0),
                "max": queue_metrics.get("queue_max", 100),
            },
            "db_status": db_status,
            "db_warn": db_warn,
            "db_schema_ready": runtime_state.db_schema_ready,
            "last_error": last_error,
            "lock_holder_pid": lock_debug.get("holder_pid"),
            "lock_idle_duration": lock_debug.get("idle_duration"),
            "models_registry_version": models_registry_version,
        })
    
    app.router.add_get("/version", version)
    app.router.add_get("/diagnostics", diagnostics)
    app.router.add_get("/health", health)
    app.router.add_get("/", root)
    app.router.add_get("/diag/webhook", diag_webhook)
    app.router.add_get("/diag/webhookinfo", diag_webhookinfo)
    app.router.add_get("/diag/lock", diag_lock)
    
    # Admin DB diagnostics routes (read from runtime_state, not app - avoid DeprecationWarning)
    try:
        from app.admin.db_diagnostics import setup_admin_routes
        from app.utils.runtime_state import runtime_state
        db_pool = getattr(runtime_state, 'db_pool', None)
        if db_pool:
            setup_admin_routes(app, db_pool)
        else:
            logger.debug("[ADMIN_DB] DB pool not available, admin routes not registered (fail-open)")
    except Exception as e:
        logger.debug(f"[ADMIN_DB] Failed to register admin routes (non-critical): {e}")
    
    # aiohttp auto-registers HEAD for GET; explicit add_head causes duplicate route
    app.router.add_post(callback_route, kie_callback)
    app.router.add_post("/webhook/{secret}", webhook)

    async def on_shutdown(_app: web.Application) -> None:
        """Graceful shutdown: close all connections and sessions."""
        logger.info("[SHUTDOWN] Starting graceful shutdown...")
        
        # Close bot session
        try:
            await bot.session.close()
            logger.info("[SHUTDOWN] ✅ Bot session closed")
        except Exception as e:
            logger.warning(f"[SHUTDOWN] Failed to close bot session: {e}")
        
        # Close database pools if available
        try:
            if runtime_state.db_pool:
                await runtime_state.db_pool.close()
                logger.info("[SHUTDOWN] ✅ Database pool closed")
        except Exception as e:
            logger.warning(f"[SHUTDOWN] Failed to close database pool: {e}")
        
        # Close KIE client sessions if any
        try:
            from app.integrations.strict_kie_client import get_kie_client
            kie_client = get_kie_client()
            if kie_client:
                await kie_client.close()
                logger.info("[SHUTDOWN] ✅ KIE client session closed")
        except Exception as e:
            logger.debug(f"[SHUTDOWN] KIE client close (may not be initialized): {e}")
        
        # Close psycopg2 connection pool
        try:
            from database import close_connection_pool
            close_connection_pool()
            logger.info("[SHUTDOWN] ✅ psycopg2 connection pool closed")
        except Exception as e:
            logger.debug(f"[SHUTDOWN] psycopg2 pool close (may not be initialized): {e}")
        
        logger.info("[SHUTDOWN] ✅ Graceful shutdown complete")

    app.on_shutdown.append(on_shutdown)
    return app


async def _start_web_server(app: web.Application, port: int) -> web.AppRunner:
    """Start aiohttp server with deterministic port binding."""
    runner = web.AppRunner(app)
    await runner.setup()
    host = "0.0.0.0"  # Always bind to all interfaces for Render
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    
    # CRITICAL: Log successful bind BEFORE background tasks
    logger.info(
        "[HTTP] ✅ Server listening on %s:%d (socket open, ready for traffic)",
        host, port
    )
    return runner


async def main() -> None:
    LOG_LEVEL_ENV = os.getenv("LOG_LEVEL", "").upper()
    setup_logging(level=(logging.DEBUG if LOG_LEVEL_ENV == "DEBUG" else logging.INFO))

    # CRITICAL: Validate ENV contract BEFORE any DB/network operations
    from app.utils.startup_validation import startup_validation
    if not startup_validation():
        logger.error("[STARTUP] ENV validation failed - exiting")
        sys.exit(1)

    cfg = _load_runtime_config()
    effective_bot_mode = cfg.bot_mode
    if effective_bot_mode == "webhook" and not cfg.webhook_base_url:
        logger.warning(
            "[CONFIG] WEBHOOK_BASE_URL missing in webhook mode; falling back to polling"
        )
        effective_bot_mode = "polling"

    runtime_state.bot_mode = effective_bot_mode
    runtime_state.last_start_time = datetime.now(timezone.utc).isoformat()

    # Get app version (git SHA or build ID) - safe, no secrets
    app_version = get_app_version()
    version_info = get_version_info()
    git_sha = version_info.get("git_sha") or version_info.get("commit", None)
    
    # OBSERVABILITY V2: STARTUP_SUMMARY
    from app.observability.v2 import log_startup_summary
    from app.observability.explain import log_startup_phase
    log_startup_summary(
        version=app_version,
        git_sha=git_sha,
        bot_mode=effective_bot_mode,
        port=cfg.port or 10000,
        webhook_base_url=cfg.webhook_base_url,
        dry_run=cfg.dry_run,
        subsystems={
            "db": bool(cfg.database_url),
            "telemetry": True,  # TelemetryMiddleware is available
            "admin": bool(cfg.database_url),  # Admin requires DB
            "queue": True,  # Queue always available
        },
        lock_state="UNKNOWN",  # Will be set after lock acquisition
    )

    # P0: MANDATORY Boot Self-Check (zero Traceback before user clicks)
    logger.info("=" * 60)
    logger.info("[BOOT SELF-CHECK] Starting mandatory checks...")
    logger.info("=" * 60)
    
    boot_check_ok = True
    
    # Check 1: Critical imports (MANDATORY)
    try:
        import main_render
        from app.telemetry.telemetry_helpers import TelemetryMiddleware
        from app.middleware.exception_middleware import ExceptionMiddleware
        # NOTE: runtime_state is imported at module level (line 34), verify it's accessible
        # Do not create local variable - use global import
        _ = runtime_state  # Verify global runtime_state is accessible
        logger.info("[BOOT CHECK] ✅ Import check: main_render, TelemetryMiddleware, ExceptionMiddleware, runtime_state")
    except ImportError as e:
        logger.error(f"[BOOT CHECK] ❌ Import check FAILED: {e}")
        boot_check_ok = False
    except Exception as e:
        logger.error(f"[BOOT CHECK] ❌ Import check ERROR: {e}")
        boot_check_ok = False
    
    # Check 2: Config validation (MANDATORY - no secrets in logs)
    try:
        # Validate required ENV vars exist (without printing values)
        required_vars = [
            "TELEGRAM_BOT_TOKEN",
            "BOT_MODE",
        ]
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var)
            if not value or not value.strip():
                missing_vars.append(var)
            else:
                # Log that var exists (but not its value)
                logger.debug(f"[BOOT CHECK] ✅ Config: {var} is set (length: {len(value)})")
        
        if missing_vars:
            logger.error(f"[BOOT CHECK] ❌ Config check FAILED: Missing required vars: {', '.join(missing_vars)}")
            boot_check_ok = False
        else:
            logger.info("[BOOT CHECK] ✅ Config check: Required ENV vars present")
        
        # Validate BOT_MODE value
        bot_mode = os.getenv("BOT_MODE", "").strip().lower()
        if bot_mode and bot_mode not in ["webhook", "polling"]:
            logger.warning(f"[BOOT CHECK] ⚠️ Config: BOT_MODE='{bot_mode}' is not 'webhook' or 'polling'")
        elif bot_mode:
            logger.info(f"[BOOT CHECK] ✅ Config: BOT_MODE='{bot_mode}'")
        
        # Validate PORT if set
        port_str = os.getenv("PORT")
        if port_str:
            try:
                port = int(port_str)
                if port < 1 or port > 65535:
                    logger.warning(f"[BOOT CHECK] ⚠️ Config: PORT={port} is out of valid range (1-65535)")
                else:
                    logger.info(f"[BOOT CHECK] ✅ Config: PORT={port}")
            except ValueError:
                logger.warning(f"[BOOT CHECK] ⚠️ Config: PORT='{port_str}' is not a valid integer")
        
    except Exception as e:
        logger.error(f"[BOOT CHECK] ❌ Config check ERROR: {e}")
        boot_check_ok = False
    
    # Check 3: Database URL format (if set) - validate format only, no connection
    if cfg.database_url:
        try:
            # Basic format validation (postgresql:// or postgres://)
            if not (cfg.database_url.startswith("postgresql://") or cfg.database_url.startswith("postgres://")):
                logger.warning(f"[BOOT CHECK] ⚠️ Config: DATABASE_URL format may be invalid (expected postgresql://...)")
            else:
                # Extract hostname for logging (safe, no credentials)
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(cfg.database_url)
                    hostname = parsed.hostname or "unknown"
                    logger.info(f"[BOOT CHECK] ✅ Config: DATABASE_URL format OK (host: {hostname})")
                except Exception:
                    logger.info("[BOOT CHECK] ✅ Config: DATABASE_URL format OK")
        except Exception as e:
            logger.warning(f"[BOOT CHECK] ⚠️ Config: DATABASE_URL validation error: {e}")
    
    # Check 4: Webhook URL format (if webhook mode)
    if cfg.bot_mode == "webhook":
        if cfg.webhook_base_url:
            if not (cfg.webhook_base_url.startswith("http://") or cfg.webhook_base_url.startswith("https://")):
                logger.warning(f"[BOOT CHECK] ⚠️ Config: WEBHOOK_BASE_URL format may be invalid (expected http:// or https://...)")
            else:
                logger.info(f"[BOOT CHECK] ✅ Config: WEBHOOK_BASE_URL format OK")
        else:
            logger.warning("[BOOT CHECK] ⚠️ Config: WEBHOOK_BASE_URL not set (webhook mode requires it)")
    
    # Check 3: Database connection (readonly, non-blocking, optional)
    # This is optional - if DB is unavailable, app can still start (fail-open)
    if cfg.database_url:
        try:
            import asyncpg
            # Quick connection test (timeout 3s, non-blocking)
            try:
                conn = await asyncio.wait_for(
                    asyncpg.connect(cfg.database_url, timeout=3),
                    timeout=5
                )
                await conn.fetchval("SELECT 1")
                await conn.close()
                logger.info("[BOOT CHECK] ✅ Database connection: OK (read-only test)")
            except asyncio.TimeoutError:
                logger.warning("[BOOT CHECK] ⚠️ Database connection: TIMEOUT (non-critical, app continues)")
            except Exception as db_err:
                logger.warning(f"[BOOT CHECK] ⚠️ Database connection: FAILED (non-critical): {db_err}")
        except ImportError:
            logger.debug("[BOOT CHECK] ℹ️ Database check: asyncpg not available, skipping")
        except Exception as e:
            logger.warning(f"[BOOT CHECK] ⚠️ Database check: ERROR (non-critical): {e}")
    else:
        logger.info("[BOOT CHECK] ℹ️ Database: Not configured (JSON storage mode)")
    
    # Final boot check summary
    logger.info("=" * 60)
    if boot_check_ok:
        logger.info("[BOOT SELF-CHECK] ✅ ALL CHECKS PASSED - Ready to start")
        log_startup_phase(phase="BOOT_CHECK", status="DONE", details="All checks passed")
    else:
        logger.error("[BOOT SELF-CHECK] ❌ SOME CHECKS FAILED - App may have limited functionality (fail-open)")
        log_startup_phase(
            phase="BOOT_CHECK",
            status="FAIL",
            details="Some checks failed",
            next_step="Review logs for specific failures and fix root cause"
        )
    logger.info("=" * 60)
    
    log_startup_phase(phase="ROUTERS_INIT", status="START")
    dp, bot = create_bot_application()
    log_startup_phase(phase="ROUTERS_INIT", status="DONE", details="Bot application created")
    
    # Verify bot identity and webhook configuration BEFORE anything else
    await verify_bot_identity(bot)
    
    # Initialize update queue manager
    from app.utils.update_queue import get_queue_manager
    queue_manager = get_queue_manager()
    logger.info("[QUEUE] Initializing update queue (max_size=%d workers=%d)", 
               queue_manager.max_size, queue_manager.num_workers)

    # IMPORTANT: the advisory lock helper in app.locking.single_instance relies on
    # the psycopg2 connection pool from database.py being initialized.
    # If we don't create the pool first, lock acquisition can fail even when no
    # other instance is running, leaving this deploy permanently PASSIVE.
    #
    # SINGLETON_LOCK_FORCE_ACTIVE (default: 1 / True for Render)
    #   - When True: if lock acquisition fails, proceed as ACTIVE anyway
    #     (assumes only one Render Web Service instance)
    #   - When False: don't proceed if lock acquisition fails
    #
    # SINGLETON_LOCK_STRICT (default: 0)
    #   - When True: exit immediately if lock acquisition fails
    #   - When False: continue in PASSIVE mode if lock acquisition fails
    if cfg.database_url:
        try:
            from database import get_connection_pool

            get_connection_pool()
        except Exception as e:
            logger.warning("[DB] Could not initialize psycopg2 pool for lock: %s", e)
    else:
        # No database URL - using JSON storage
        runtime_state.db_schema_ready = True  # JSON storage doesn't need migrations

    # Create lock object and state tracker
    lock = SingletonLock(cfg.database_url)
    active_state = ActiveState(active=False)  # Start as passive, will activate after lock
    
    # DEPLOY_TOPOLOGY: Log instance topology explanation
    # NOTE: os is already imported at module level (line 20), do not import again
    from app.observability.explain import log_deploy_topology
    from app.locking.single_instance import get_lock_key, get_lock_debug_info
    
    instance_id = runtime_state.instance_id
    pid = os.getpid()
    boot_time = datetime.now(timezone.utc).isoformat()
    commit_sha = app_version
    render_service_name = os.getenv("RENDER_SERVICE_NAME") or os.getenv("SERVICE_NAME")
    
    # Get lock info if available
    lock_key = None
    lock_holder_pid = None
    try:
        lock_key = get_lock_key()
        lock_debug = get_lock_debug_info()
        lock_holder_pid = lock_debug.get("holder_pid")
    except Exception:
        pass  # Lock info not available yet
    
    log_deploy_topology(
        instance_id=instance_id,
        pid=pid,
        boot_time=boot_time,
        commit_sha=commit_sha,
        is_active=False,  # Will be updated when lock acquired
        lock_key=lock_key,
        lock_holder_pid=lock_holder_pid,
        render_service_name=render_service_name,
    )
    
    # Configure queue manager with dp, bot, and active_state BEFORE starting workers
    queue_manager.configure(dp, bot, active_state)
    
    # 🔧 BACKGROUND TASKS: migrations + lock acquisition (NON-BLOCKING)
    # This ensures HTTP server starts IMMEDIATELY without waiting
    async def background_initialization():
        """Initialize lock acquisition in background (migrations moved to ACTIVE only)."""
        # Migrations moved to init_active_services (ONLY on ACTIVE)
        # PASSIVE instances must NOT run migrations - only ACTIVE should modify schema
        # This prevents concurrent migration attempts and schema conflicts
        logger.debug("[MIGRATIONS] Migrations deferred to ACTIVE mode (init_active_services)")
        # Mark schema as unknown until ACTIVE instance applies migrations
        runtime_state.db_schema_ready = False
        
        # PHASE 5: Start orphan callback reconciliation background task
        if runtime_state.db_schema_ready and cfg.database_url:
            try:
                # Create storage instance for reconciler
                from app.storage import get_storage
                storage_instance = get_storage()
                
                reconciler = OrphanCallbackReconciler(
                    storage=storage_instance,
                    bot=bot,
                    check_interval=10,
                    max_age_minutes=30
                )
                await reconciler.start()
                logger.info("[RECONCILER] ✅ Background orphan reconciliation started (10s interval, 30min timeout)")
            except Exception as exc:
                logger.warning(f"[RECONCILER] ⚠️ Failed to start reconciler: {exc}")
        
        # PHASE 5.5: Start FSM state cleanup background task (ONLY on ACTIVE)
        async def fsm_cleanup_loop():
            """Periodic cleanup of expired FSM states."""
            while True:
                try:
                    await asyncio.sleep(300)  # Run every 5 minutes
                    if not active_state.active:
                        continue  # Only cleanup on ACTIVE instance
                    
                    if runtime_state.db_pool:
                        try:
                            from app.database.services import DatabaseService, UIStateService
                            from datetime import datetime, timezone
                            db_service = DatabaseService(cfg.database_url)
                            db_service._pool = runtime_state.db_pool
                            ui_state_service = UIStateService(db_service)
                            await ui_state_service.cleanup_expired()
                            # Track last run time for health check
                            runtime_state.fsm_cleanup_last_run = datetime.now(timezone.utc).isoformat()
                        except Exception as e:
                            logger.debug(f"[FSM_CLEANUP] Failed to cleanup expired states: {e}")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    from app.utils.correlation import correlation_tag
                    cid = correlation_tag()
                    logger.warning(f"{cid} [FSM_CLEANUP] Error in cleanup loop: {e}")
                    await asyncio.sleep(60)  # Wait before retry
        
        asyncio.create_task(fsm_cleanup_loop())
        logger.info("[FSM_CLEANUP] ✅ Background FSM state cleanup started (5min interval)")
        
        # PHASE 5.6: Start stale job cleanup background task (ONLY on ACTIVE)
        async def stale_job_cleanup_loop():
            """Periodic cleanup of stale jobs (running >30min)."""
            while True:
                try:
                    await asyncio.sleep(600)  # Run every 10 minutes
                    if not active_state.active:
                        continue  # Only cleanup on ACTIVE instance
                    
                    if runtime_state.db_pool:
                        try:
                            from app.services.job_service_v2 import JobServiceV2
                            from datetime import datetime, timezone
                            job_service = JobServiceV2(runtime_state.db_pool)
                            cleaned = await job_service.cleanup_stale_jobs(stale_minutes=30)
                            if cleaned > 0:
                                logger.info(f"[STALE_JOB_CLEANUP] Cleaned up {cleaned} stale jobs")
                            # Track last run time for health check
                            runtime_state.stale_job_cleanup_last_run = datetime.now(timezone.utc).isoformat()
                        except Exception as e:
                            logger.warning(f"[STALE_JOB_CLEANUP] Failed to cleanup stale jobs: {e}")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning(f"[STALE_JOB_CLEANUP] Error in cleanup loop: {e}")
                    await asyncio.sleep(60)  # Wait before retry
        
        asyncio.create_task(stale_job_cleanup_loop())
        logger.info("[STALE_JOB_CLEANUP] ✅ Background stale job cleanup started (10min interval)")
        
        # PHASE 5.7: Start stuck payment cleanup background task (ONLY on ACTIVE)
        async def stuck_payment_cleanup_loop():
            """Periodic cleanup of stuck payments (pending >24h)."""
            while True:
                try:
                    await asyncio.sleep(3600)  # Run every hour
                    if not active_state.active:
                        continue  # Only cleanup on ACTIVE instance
                    
                    if runtime_state.db_pool:
                        try:
                            from app.storage import get_storage
                            from datetime import datetime, timezone
                            storage = get_storage()
                            if hasattr(storage, 'cleanup_stuck_payments'):
                                cleaned = await storage.cleanup_stuck_payments(stale_hours=24)
                                if cleaned > 0:
                                    logger.info(f"[STUCK_PAYMENT_CLEANUP] Cleaned up {cleaned} stuck payments")
                                # Track last run time for health check
                                runtime_state.stuck_payment_cleanup_last_run = datetime.now(timezone.utc).isoformat()
                        except Exception as e:
                            from app.utils.correlation import correlation_tag
                            cid = correlation_tag()
                            logger.warning(f"{cid} [STUCK_PAYMENT_CLEANUP] Failed to cleanup stuck payments: {e}")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    from app.utils.correlation import correlation_tag
                    cid = correlation_tag()
                    logger.warning(f"{cid} [STUCK_PAYMENT_CLEANUP] Error in cleanup loop: {e}")
                    await asyncio.sleep(60)  # Wait before retry
        
        asyncio.create_task(stuck_payment_cleanup_loop())
        logger.info("[STUCK_PAYMENT_CLEANUP] ✅ Background stuck payment cleanup started (1h interval)")
        
        # Start update queue workers (already configured above)
        await queue_manager.start()
        logger.info("[QUEUE] ✅ Workers started (background update processing)")
        
        # PHASE 6: Webhook setup moved to init_active_services (ONLY on ACTIVE)
        # PASSIVE instances must NOT set webhook - only ACTIVE should own it
        # This prevents race conditions and ensures single webhook owner
        logger.debug("[WEBHOOK] Webhook setup deferred to ACTIVE mode (init_active_services)")
        
        # Define init_active_services BEFORE lock_controller creation
        # db_service declared at function level for finally block
        free_manager = None

        async def init_active_services() -> None:
            """Initialize services when lock acquired (called by controller callback)"""
            nonlocal db_service, free_manager
            
            logger.info("[INIT_SERVICES] 🚀 init_active_services() CALLED (ACTIVE MODE)")
            logger.info(f"[INIT_SERVICES] BOT_MODE={effective_bot_mode}, DRY_RUN={cfg.dry_run}")

            # Update runtime state
            # active_state synced automatically by lock_controller, no need to set manually
            runtime_state.lock_acquired = True
            
            # P0-1: Update DEPLOY_TOPOLOGY with correct ACTIVE state
            # NOTE: os is already imported at module level (line 20), do not import again
            from app.observability.explain import log_deploy_topology
            from app.locking.single_instance import get_lock_key, get_lock_debug_info
            try:
                lock_key = get_lock_key()
                lock_debug = get_lock_debug_info()
                lock_holder_pid = lock_debug.get("holder_pid")
                render_service_name = os.getenv("RENDER_SERVICE_NAME") or os.getenv("SERVICE_NAME")
                
                log_deploy_topology(
                    instance_id=runtime_state.instance_id,
                    pid=os.getpid(),
                    boot_time=runtime_state.last_start_time or datetime.now(timezone.utc).isoformat(),
                    commit_sha=app_version,
                    is_active=True,  # Now ACTIVE
                    lock_key=lock_key,
                    lock_holder_pid=lock_holder_pid,
                    render_service_name=render_service_name,
                )
            except Exception as e:
                logger.debug(f"[DEPLOY_TOPOLOGY] Failed to log topology update: {e}")
            
            # Step 1: Apply migrations (ONLY on ACTIVE instance)
            log_startup_phase(phase="DB_INIT", status="START")
            if cfg.database_url:
                logger.info("[INIT_SERVICES] Applying database migrations (ACTIVE only)...")
                try:
                    from app.storage.migrations import apply_migrations_safe
                    migrations_ok = await apply_migrations_safe(cfg.database_url)
                    if migrations_ok:
                        logger.info("[MIGRATIONS] ✅ Database schema ready")
                        runtime_state.db_schema_ready = True
                        log_startup_phase(phase="DB_INIT", status="DONE", details="Migrations applied successfully")
                    else:
                        logger.error("[MIGRATIONS] ❌ Schema NOT ready")
                        runtime_state.db_schema_ready = False
                        log_startup_phase(
                            phase="DB_INIT",
                            status="FAIL",
                            details="Migrations failed",
                            next_step="Check database connectivity and migration scripts"
                        )
                except Exception as e:
                    logger.exception(f"[MIGRATIONS] CRITICAL: Auto-apply failed: {e}")
                    runtime_state.db_schema_ready = False
                    log_startup_phase(
                        phase="DB_INIT",
                        status="FAIL",
                        details=f"Exception: {e}",
                        next_step="Review migration logs and database state"
                    )
            else:
                runtime_state.db_schema_ready = True  # JSON storage doesn't need migrations
                log_startup_phase(phase="DB_INIT", status="DONE", details="Skipped (JSON storage mode)")
            
            # Step 2: WEBHOOK ON ACTIVE: Ensure webhook is set on ACTIVE instance
            # This guarantees webhook ownership after lock acquired
            if effective_bot_mode == "webhook" and not cfg.dry_run:
                logger.info("[WEBHOOK_ACTIVE] 🔧 Ensuring webhook on ACTIVE instance...")
                webhook_url = _build_webhook_url(cfg)
                if webhook_url:
                    from app.utils.webhook import ensure_webhook
                    try:
                        webhook_set = await ensure_webhook(
                            bot,
                            webhook_url=webhook_url,
                            secret_token=cfg.webhook_secret_token or None,
                            force_reset=False,  # No force - respect no-op logic
                        )
                        if webhook_set:
                            logger.info("[WEBHOOK_ACTIVE] ✅ Webhook ensured on ACTIVE instance")
                        else:
                            logger.warning("[WEBHOOK_ACTIVE] ⚠️ Webhook ensure returned False")
                    except Exception as e:
                        logger.exception("[WEBHOOK_ACTIVE] ❌ Exception: %s", e)
                else:
                    logger.error("[WEBHOOK_ACTIVE] ❌ Cannot build webhook URL!")

            # Step 3: Initialize database services (ONLY on ACTIVE)
            if cfg.database_url:
                logger.info("[INIT_SERVICES] Initializing DatabaseService...")
                try:
                    from app.database.services import DatabaseService
                    from app.free.manager import FreeModelManager

                    db_service = DatabaseService(cfg.database_url)
                    await db_service.initialize()
                    free_manager = FreeModelManager(db_service)

                    from bot.handlers.balance import set_database_service as set_balance_db
                    from bot.handlers.history import set_database_service as set_history_db
                    from bot.handlers.marketing import (
                        set_database_service as set_marketing_db,
                        set_free_manager,
                    )

                    set_balance_db(db_service)
                    set_history_db(db_service)
                    set_marketing_db(db_service)
                    set_free_manager(free_manager)

                    # Initialize AdminService and inject into admin handlers
                    from app.admin.service import AdminService
                    from app.services.wiring import set_services as set_global_services
                    from bot.handlers.admin import set_services as set_admin_handlers_services
                    
                    admin_service = AdminService(db_service, free_manager)
                    # Single source of truth: set in global wiring
                    set_global_services(db_service, admin_service, free_manager)
                    # Also set in admin handlers (backward compatibility)
                    set_admin_handlers_services(db_service, admin_service, free_manager)
                    logger.info("[ADMIN] ✅ AdminService initialized and injected into handlers")

                    # Initialize observability events DB
                    from app.observability.events_db import init_events_db
                    if hasattr(db_service, '_pool') and db_service._pool:
                        init_events_db(db_service._pool)
                        logger.info("[OBSERVABILITY] ✅ Events DB initialized")
                    
                    # Store pool in runtime_state instead of app (avoid DeprecationWarning)
                    # Admin routes will read from runtime_state or use dependency injection
                    if hasattr(db_service, '_pool'):
                        # Store in runtime_state for admin endpoints (fail-open if not available)
                        runtime_state.db_pool = db_service._pool

                    logger.info("[DB] ✅ DatabaseService initialized and injected into handlers")
                except Exception as e:
                    logger.exception("[DB] ❌ Database init failed: %s", e)
                    db_service = None
        
        # Step 2: Start unified lock controller with callback + active_state sync
        from app.locking.controller import SingletonLockController
        
        lock_controller = SingletonLockController(
            lock, 
            bot, 
            on_active_callback=init_active_services,
            active_state=active_state  # CRITICAL: pass same object for sync
        )
        active_state.lock_controller = lock_controller  # Store for webhook access
        
        await lock_controller.start()
        
        # Initial sync (lock_controller will call active_state.set() in _set_state)
        initial_should_process = lock_controller.should_process_updates()
        runtime_state.lock_acquired = initial_should_process
        
        if initial_should_process:
            logger.info("[LOCK_CONTROLLER] ✅ ACTIVE MODE (lock acquired immediately)")
        else:
            logger.info("[LOCK_CONTROLLER] ⏸️ PASSIVE MODE (background watcher started)")

    runner: Optional[web.AppRunner] = None
    # Import DatabaseService type for annotation
    try:
        from app.database.services import DatabaseService as _DatabaseService
    except ImportError:
        _DatabaseService = None  # type: ignore
    db_service: Optional[_DatabaseService] = None  # type: ignore
    
    async def state_sync_loop() -> None:
        """
        Monitor active_state sync with lock_controller + safety-net for stale PASSIVE.
        If lock acquired but active_state still False after 3s → force ACTIVE.
        """
        logger.info("[STATE_SYNC] 🔄 Started, initial active=%s", active_state.active)
        lock_acquired_time = None  # Track when lock_controller first reports ACTIVE
        
        while True:
            await asyncio.sleep(1)
            if hasattr(active_state, 'lock_controller'):
                new_active = active_state.lock_controller.should_process_updates()
                
                # 🚨 SAFETY-NET: Detect stale PASSIVE state
                if new_active and not active_state.active:
                    # lock_controller says ACTIVE, but active_state is still False
                    if lock_acquired_time is None:
                        lock_acquired_time = time.time()
                        logger.warning(
                            "[STATE_SYNC] ⚠️ lock_controller ACTIVE but active_state False (start monitoring)"
                        )
                    elif time.time() - lock_acquired_time > 3.0:
                        # Still not synced after 3 seconds → FORCE
                        logger.error(
                            "[STATE_SYNC] ⚠️⚠️ lock acquired but active_state still False for 3s → FORCING ACTIVE"
                        )
                        active_state.set(True, reason="safety_net_force")
                        runtime_state.lock_acquired = True
                        lock_acquired_time = None  # Reset
                elif not new_active:
                    # Reset safety-net timer if lock lost
                    lock_acquired_time = None
                
                # Normal sync (this should now be redundant if lock_controller._set_state works)
                if new_active != active_state.active:
                    old_active = active_state.active
                    logger.warning(
                        "[STATE_SYNC] ⚠️ Manual sync needed: %s -> %s (lock_controller didn't call active_state.set?)",
                        old_active, new_active
                    )
                    if new_active:
                        active_state.set(True, reason="state_sync_fallback")
                    else:
                        active_state.set(False, reason="state_sync_fallback")
                    runtime_state.lock_acquired = new_active
                    lock_acquired_time = None  # Reset safety-net

    # 🚀 START BACKGROUND INITIALIZATION (non-blocking)
    asyncio.create_task(background_initialization())
    asyncio.create_task(state_sync_loop())  # Sync active_state with controller

    try:
        if effective_bot_mode == "polling":
            # Create app and start HTTP server IMMEDIATELY
            app = _make_web_app(dp=dp, bot=bot, cfg=cfg, active_state=active_state)
            if cfg.port:
                runner = await _start_web_server(app, cfg.port)
                logger.info("[HEALTH] ✅ Server started on port %s (migrations/lock in background)", cfg.port)

            # Wait briefly for background init (but don't block)
            await asyncio.sleep(0.5)

            # If passive mode, keep healthcheck running
            if not active_state.active:
                logger.info("[PASSIVE MODE] HTTP server running, state_sync_loop monitors lock")
                await asyncio.Event().wait()
                return

            # Active mode: initialize services and start polling
            # (init_active_services called by state_sync_loop on PASSIVE→ACTIVE)
            await preflight_webhook(bot)
            await dp.start_polling(bot)
            return

        # webhook mode - START HTTP SERVER IMMEDIATELY
        app = _make_web_app(dp=dp, bot=bot, cfg=cfg, active_state=active_state)
        if cfg.port:
            runner = await _start_web_server(app, cfg.port)
            logger.info("[HEALTH] ✅ Server started on port %s (migrations/lock in background)", cfg.port)

        # Wait briefly for background init (but don't block)
        await asyncio.sleep(0.5)

        # Initialize active services if lock acquired
        # (init_active_services called by state_sync_loop on PASSIVE→ACTIVE)
        if not active_state.active:
            logger.info("[PASSIVE MODE] HTTP server running, state_sync_loop monitors lock")

        await asyncio.Event().wait()
    finally:
        try:
            if runner is not None:
                await runner.cleanup()
        except Exception:
            pass
        try:
            await bot.session.close()
        except Exception:
            pass
        try:
            # db_service may not be initialized if we exited early
            try:
                if db_service is not None:
                    await db_service.close()
            except NameError:
                pass  # db_service was never created
        except Exception:
            pass
        try:
            await lock.release()
        except Exception:
            pass

        # Close sync pool used by advisory lock (best-effort)
        try:
            from database import close_connection_pool

            close_connection_pool()
        except Exception:
            pass


if __name__ == "__main__":

    asyncio.run(main())
