"""
Job Service - атомарные операции с jobs table (unified schema)

CRITICAL INVARIANTS:
1. Users MUST exist before jobs
2. Jobs created with idempotency_key (duplicate-safe)
3. Balance operations atomic with job creation
4. Callbacks never lost (orphan reconciliation)
5. Telegram delivery guaranteed (retry logic)
"""

import logging
import uuid
from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False

from app.storage.status import normalize_job_status

logger = logging.getLogger(__name__)


class JobServiceV2:
    """
    Production-ready job service following felores/kie-ai-mcp-server patterns.
    
    Key features:
    - Atomic job creation (user check → balance hold → job insert → KIE task)
    - Idempotent operations (duplicate requests handled gracefully)
    - No orphan jobs (strict lifecycle management)
    - Guaranteed delivery (chat_id + retry logic)
    """
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
    
    async def create_job_atomic(
        self,
        user_id: int,
        model_id: str,
        category: str,
        input_params: Dict[str, Any],
        price_rub: Decimal,
        chat_id: Optional[int] = None,
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Atomic job creation following STRICT lifecycle:
        1. Validate user exists (FK enforcement)
        2. Check idempotency (duplicate safety)
        3. Hold balance (if price > 0)
        4. Insert job (status='pending')
        5. Return job for KIE task creation
        
        CRITICAL: Job created BEFORE calling KIE API to avoid orphan callbacks.
        
        Returns:
            {
                'id': int,
                'user_id': int,
                'model_id': str,
                'idempotency_key': str,
                'status': 'pending',
                ...
            }
        
        Raises:
            ValueError: User not found, invalid input
            InsufficientFundsError: Balance too low
        """
        if not idempotency_key:
            idempotency_key = f"job:{user_id}:{uuid.uuid4()}"
        
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # PHASE 1: Check if already exists (idempotency)
                existing = await conn.fetchrow(
                    "SELECT * FROM jobs WHERE idempotency_key = $1",
                    idempotency_key
                )
                if existing:
                    from app.utils.correlation import correlation_tag
                    cid = correlation_tag()
                    logger.info(f"{cid} [JOB] Idempotent duplicate: key={idempotency_key} id={existing['id']}")
                    return dict(existing)
                
                # PHASE 2: Validate user exists (enforces FK)
                user = await conn.fetchrow(
                    "SELECT user_id FROM users WHERE user_id = $1",
                    user_id
                )
                if not user:
                    from app.utils.correlation import correlation_tag
                    cid = correlation_tag()
                    logger.error(f"{cid} [JOB] User {user_id} not found - create user first")
                    raise ValueError(f"User {user_id} not found - create user first")
                
                # PHASE 3: Check balance if paid model
                if price_rub > 0:
                    wallet = await conn.fetchrow(
                        "SELECT balance_rub, hold_rub FROM wallets WHERE user_id = $1",
                        user_id
                    )
                    if not wallet:
                        # Auto-create wallet if missing
                        await conn.execute(
                            "INSERT INTO wallets (user_id, balance_rub) VALUES ($1, 0.00)",
                            user_id
                        )
                        wallet = {'balance_rub': Decimal('0.00'), 'hold_rub': Decimal('0.00')}
                    
                    available = wallet['balance_rub'] - wallet['hold_rub']
                    if available < price_rub:
                        raise InsufficientFundsError(
                            f"Insufficient funds: need {price_rub} RUB, have {available} RUB"
                        )
                    
                    # PHASE 4: Hold balance (prevents double-spend)
                    await conn.execute("""
                        UPDATE wallets
                        SET hold_rub = hold_rub + $2,
                            updated_at = NOW()
                        WHERE user_id = $1
                    """, user_id, price_rub)
                    
                    # Record hold in ledger (for audit trail)
                    await conn.execute("""
                        INSERT INTO ledger (user_id, kind, amount_rub, status, ref, meta)
                        VALUES ($1, 'hold', $2, 'done', $3, $4)
                    """, user_id, price_rub, idempotency_key, {
                        'model_id': model_id,
                        'category': category
                    })
                
                # PHASE 5: Validate and serialize input_params (prevent DoS via large JSON)
                import json
                try:
                    input_json = json.dumps(input_params, ensure_ascii=False)
                    # CRITICAL: Limit JSON size to prevent DoS (10MB max)
                    MAX_JSON_SIZE = 10 * 1024 * 1024  # 10MB
                    if len(input_json.encode('utf-8')) > MAX_JSON_SIZE:
                        from app.utils.correlation import correlation_tag
                        cid = correlation_tag()
                        logger.error(f"{cid} [JOB] Input params JSON too large: {len(input_json.encode('utf-8'))} bytes (max {MAX_JSON_SIZE})")
                        raise ValueError(f"Input params JSON too large: {len(input_json.encode('utf-8'))} bytes (max {MAX_JSON_SIZE})")
                except (TypeError, ValueError) as e:
                    from app.utils.correlation import correlation_tag
                    cid = correlation_tag()
                    logger.error(f"{cid} [JOB] Invalid input_params for job: {e}")
                    raise ValueError(f"Invalid job input_params: {e}")
                
                # PHASE 6: Create job (status='pending')
                job = await conn.fetchrow("""
                    INSERT INTO jobs (
                        user_id, model_id, category, input_json, price_rub,
                        status, idempotency_key, chat_id, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, 'pending', $6, $7, NOW())
                    RETURNING *
                """, user_id, model_id, category, input_json, price_rub,
                     idempotency_key, chat_id)
                
                logger.info(
                    f"[JOB_CREATE] id={job['id']} user={user_id} model={model_id} "
                    f"price={price_rub} status=pending"
                )
                
                return dict(job)
    
    async def update_with_kie_task(
        self,
        job_id: int,
        kie_task_id: str,
        status: str = 'running'
    ) -> None:
        """
        Update job with KIE task_id after successful API call.
        
        Lifecycle: pending → running
        
        CRITICAL: Only update if job is in non-terminal status.
        """
        from app.storage.status import is_terminal_status
        
        normalized_status = normalize_job_status(status)
        
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Check current status (with lock to prevent race)
                current_job = await conn.fetchrow(
                    "SELECT status FROM jobs WHERE id = $1 FOR UPDATE",
                    job_id
                )
                
                if not current_job:
                    from app.utils.correlation import correlation_tag
                    cid = correlation_tag()
                    logger.warning(f"{cid} [JOB_UPDATE] Job {job_id} not found for task update")
                    return
                
                current_status = current_job['status']
                
                # Prevent updating terminal jobs
                if is_terminal_status(current_status):
                    from app.utils.correlation import correlation_tag
                    cid = correlation_tag()
                    logger.warning(
                        f"{cid} [JOB_UPDATE] Ignoring task update for job {job_id}: already in terminal status {current_status}"
                    )
                    return
                
                # Update job
                await conn.execute("""
                    UPDATE jobs
                    SET kie_task_id = $2,
                        status = $3,
                        updated_at = NOW()
                    WHERE id = $1
                """, job_id, kie_task_id, normalized_status)
                
                logger.info(f"[JOB_UPDATE] id={job_id} task={kie_task_id} status={normalized_status} (from {current_status})")
    
    async def update_from_callback(
        self,
        job_id: int,
        status: str,
        result_json: Optional[Dict[str, Any]] = None,
        error_text: Optional[str] = None,
        kie_status: Optional[str] = None
    ) -> None:
        """
        Update job from KIE callback.
        
        Lifecycle: running → done/failed
        
        CRITICAL: If status='done', also release held balance.
        """
        from app.storage.status import is_terminal_status
        
        normalized_status = normalize_job_status(status)
        
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # CRITICAL: Check job exists and get current status (with lock to prevent race)
                job = await conn.fetchrow(
                    "SELECT user_id, price_rub, idempotency_key, status FROM jobs WHERE id = $1 FOR UPDATE",
                    job_id
                )
                if not job:
                    from app.utils.correlation import correlation_tag
                    cid = correlation_tag()
                    logger.warning(f"{cid} [JOB_UPDATE] Job {job_id} not found")
                    return
                
                current_status = job['status']
                
                # CRITICAL: Prevent invalid transitions from terminal statuses
                if is_terminal_status(current_status):
                    from app.utils.correlation import correlation_tag
                    cid = correlation_tag()
                    logger.warning(
                        f"{cid} [JOB_UPDATE] Ignoring callback for job {job_id}: already in terminal status {current_status}, "
                        f"attempted transition to {normalized_status}"
                    )
                    return
                
                # Update job (only if not already terminal)
                await conn.execute("""
                    UPDATE jobs
                    SET status = $2,
                        kie_status = $3,
                        result_json = $4,
                        error_text = $5,
                        finished_at = CASE WHEN $2 IN ('done', 'failed', 'canceled') THEN NOW() ELSE finished_at END,
                        updated_at = NOW()
                    WHERE id = $1
                """, job_id, normalized_status, kie_status, result_json, error_text)
                
                # Get job data (already fetched above)
                user_id = job['user_id']
                price_rub = job['price_rub']
                
                if normalized_status == 'done' and price_rub > 0:
                    # Get balance BEFORE charge (for logging)
                    wallet_before = await conn.fetchrow(
                        "SELECT balance_rub, hold_rub FROM wallets WHERE user_id = $1",
                        user_id
                    )
                    balance_before = wallet_before['balance_rub'] if wallet_before else Decimal('0.00')
                    hold_before = wallet_before['hold_rub'] if wallet_before else Decimal('0.00')
                    
                    # SUCCESS: Release hold + charge balance
                    await conn.execute("""
                        UPDATE wallets
                        SET balance_rub = balance_rub - $2,
                            hold_rub = hold_rub - $2,
                            updated_at = NOW()
                        WHERE user_id = $1
                    """, user_id, price_rub)
                    
                    # Get balance AFTER charge (for logging)
                    wallet_after = await conn.fetchrow(
                        "SELECT balance_rub, hold_rub FROM wallets WHERE user_id = $1",
                        user_id
                    )
                    balance_after = wallet_after['balance_rub'] if wallet_after else Decimal('0.00')
                    hold_after = wallet_after['hold_rub'] if wallet_after else Decimal('0.00')
                    
                    # Record charge in ledger
                    await conn.execute("""
                        INSERT INTO ledger (user_id, kind, amount_rub, status, ref, meta)
                        VALUES ($1, 'charge', $2, 'done', $3, $4)
                    """, user_id, price_rub, f"job:{job_id}", {
                        'job_id': job_id,
                        'idempotency_key': job['idempotency_key']
                    })
                    
                    logger.info(
                        f"[BALANCE_CHARGE] user={user_id} job={job_id} price={price_rub} "
                        f"balance_before={balance_before} balance_after={balance_after} "
                        f"hold_before={hold_before} hold_after={hold_after}"
                    )
                
                elif normalized_status in ('failed', 'canceled') and price_rub > 0:
                    # Get balance BEFORE release (for logging)
                    wallet_before = await conn.fetchrow(
                        "SELECT balance_rub, hold_rub FROM wallets WHERE user_id = $1",
                        user_id
                    )
                    balance_before = wallet_before['balance_rub'] if wallet_before else Decimal('0.00')
                    hold_before = wallet_before['hold_rub'] if wallet_before else Decimal('0.00')
                    
                    # FAILURE: Release hold (no charge)
                    # CRITICAL: Use direct SQL within transaction for atomicity with job update
                    # Note: WalletService.release would require separate transaction, breaking atomicity
                    # This is safe because we're already in a transaction with FOR UPDATE lock
                    ref = f"job:{job_id}:refund"
                    
                    # Check idempotency: if release already exists in ledger, skip
                    existing_release = await conn.fetchval(
                        "SELECT id FROM ledger WHERE ref = $1 AND kind = 'release' AND status = 'done'",
                        ref
                    )
                    if existing_release:
                        logger.info(f"[JOB_REFUND] Release {ref} already processed (idempotent)")
                    else:
                        # Release hold
                        await conn.execute("""
                            UPDATE wallets
                            SET hold_rub = hold_rub - $2,
                                updated_at = NOW()
                            WHERE user_id = $1
                        """, user_id, price_rub)
                        
                        # Record release in ledger for idempotency
                        await conn.execute("""
                            INSERT INTO ledger (user_id, kind, amount_rub, status, ref, meta)
                            VALUES ($1, 'release', $2, 'done', $3, $4)
                        """, user_id, price_rub, ref, {
                            'job_id': job_id,
                            'reason': 'job_failed'
                        })
                    
                    # Get balance AFTER release (for logging)
                    wallet_after = await conn.fetchrow(
                        "SELECT balance_rub, hold_rub FROM wallets WHERE user_id = $1",
                        user_id
                    )
                    balance_after = wallet_after['balance_rub'] if wallet_after else Decimal('0.00')
                    hold_after = wallet_after['hold_rub'] if wallet_after else Decimal('0.00')
                    
                    logger.info(
                        f"[BALANCE_REFUND] user={user_id} job={job_id} price={price_rub} "
                        f"balance_before={balance_before} balance_after={balance_after} "
                        f"hold_before={hold_before} hold_after={hold_after}"
                    )
                
                logger.info(f"[JOB_CALLBACK] id={job_id} status={normalized_status}")
    
    async def mark_delivered(self, job_id: int) -> None:
        """Mark job result as delivered to Telegram."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE jobs
                SET delivered_at = NOW(),
                    updated_at = NOW()
                WHERE id = $1
            """, job_id)
            
            logger.info(f"[TELEGRAM_DELIVERY] job={job_id} delivered=True")
    
    async def get_by_id(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Get job by ID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
            return dict(row) if row else None
    
    async def get_by_task_id(self, kie_task_id: str) -> Optional[Dict[str, Any]]:
        """Get job by KIE task_id (for callbacks)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM jobs WHERE kie_task_id = $1", kie_task_id)
            return dict(row) if row else None
    
    async def get_by_idempotency_key(self, key: str) -> Optional[Dict[str, Any]]:
        """Get job by idempotency_key."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM jobs WHERE idempotency_key = $1", key)
            return dict(row) if row else None
    
    async def cleanup_stale_jobs(self, stale_minutes: int = 30) -> int:
        """
        Cleanup stale jobs (running for more than stale_minutes).
        
        CRITICAL: Marks stale jobs as 'failed' and releases held balance.
        This prevents jobs from hanging forever if callback is lost.
        
        Returns:
            Number of jobs cleaned up
        """
        from app.storage.status import normalize_job_status
        
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Find stale running jobs
                # CRITICAL: Use index idx_jobs_status_updated_at for optimal performance
                stale_jobs = await conn.fetch("""
                    SELECT id, user_id, price_rub, idempotency_key
                    FROM jobs
                    WHERE status = 'running'
                      AND updated_at < NOW() - INTERVAL '%s minutes'
                    FOR UPDATE
                """, stale_minutes)
                
                if not stale_jobs:
                    return 0
                
                from app.utils.correlation import correlation_tag
                cid = correlation_tag()
                logger.warning(f"{cid} [JOB_CLEANUP] Found {len(stale_jobs)} stale jobs (running >{stale_minutes}min)")
                
                cleaned_count = 0
                for job in stale_jobs:
                    job_id = job['id']
                    user_id = job['user_id']
                    price_rub = job['price_rub']
                    
                    # Mark as failed
                    await conn.execute("""
                        UPDATE jobs
                        SET status = 'failed',
                            error_text = 'Job timeout: no callback received after ' || $2 || ' minutes',
                            finished_at = NOW(),
                            updated_at = NOW()
                        WHERE id = $1
                    """, job_id, stale_minutes)
                    
                    # Release held balance (if any)
                    if price_rub > 0:
                        # Check if hold exists for this job
                        hold_ref = f"job:{job_id}"
                        hold_exists = await conn.fetchval(
                            "SELECT 1 FROM ledger WHERE ref = $1 AND kind = 'hold' AND status = 'done'",
                            hold_ref
                        )
                        
                        if hold_exists:
                            # Release hold back to balance
                            await conn.execute("""
                                UPDATE wallets
                                SET balance_rub = balance_rub + $2,
                                    hold_rub = hold_rub - $2,
                                    updated_at = NOW()
                                WHERE user_id = $1
                            """, user_id, price_rub)
                            
                            # Record release in ledger
                            await conn.execute("""
                                INSERT INTO ledger (user_id, kind, amount_rub, status, ref, meta)
                                VALUES ($1, 'release', $2, 'done', $3, $4)
                            """, user_id, price_rub, hold_ref, {'reason': 'stale_job_cleanup', 'job_id': job_id})
                            
                            logger.info(
                                f"[JOB_CLEANUP] Released hold for stale job {job_id}: "
                                f"user={user_id} amount={price_rub}"
                            )
                    
                    cleaned_count += 1
                
                logger.info(f"[JOB_CLEANUP] ✅ Cleaned up {cleaned_count} stale jobs")
                return cleaned_count
    
    async def list_user_jobs(
        self,
        user_id: int,
        limit: int = 20,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List user's jobs (for history)."""
        async with self.pool.acquire() as conn:
            if status:
                rows = await conn.fetch("""
                    SELECT * FROM jobs
                    WHERE user_id = $1 AND status = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                """, user_id, normalize_job_status(status), limit)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM jobs
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                """, user_id, limit)
            
            return [dict(row) for row in rows]
    
    async def list_undelivered(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get jobs that are done but not delivered (for retry).
        
        Use case: Telegram API was down, retry delivery.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM jobs
                WHERE status = 'done'
                  AND delivered_at IS NULL
                  AND chat_id IS NOT NULL
                  AND finished_at IS NOT NULL
                ORDER BY finished_at ASC
                LIMIT $1
            """, limit)
            
            return [dict(row) for row in rows]


class InsufficientFundsError(Exception):
    """Raised when user doesn't have enough balance."""
    pass
