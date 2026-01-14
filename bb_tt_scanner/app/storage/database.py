"""SQLite database for storing signals journal"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from loguru import logger


class Database:
    """SQLite database manager for signals journal"""
    
    def __init__(self, db_path: str = "bb_scanner.db"):
        self.db_path = Path(db_path)
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Signals journal table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                match_id TEXT NOT NULL,
                match_name TEXT,
                reason TEXT,
                main_market TEXT,
                main_odds REAL,
                main_sum REAL,
                hedge_market TEXT,
                hedge_odds REAL,
                hedge_sum REAL,
                pnl_data TEXT,
                raw_data TEXT
            )
        """)
        
        # Index for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_match_timestamp 
            ON signals(match_id, timestamp)
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized: {self.db_path}")
    
    def save_signal(
        self,
        match_id: str,
        match_name: str,
        reason: str,
        main_market: str,
        main_odds: float,
        main_sum: float,
        hedge_market: Optional[str],
        hedge_odds: Optional[float],
        hedge_sum: Optional[float],
        pnl_data: Dict[str, Any],
        raw_data: Optional[Dict[str, Any]] = None
    ):
        """Save signal to journal"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO signals (
                timestamp, match_id, match_name, reason,
                main_market, main_odds, main_sum,
                hedge_market, hedge_odds, hedge_sum,
                pnl_data, raw_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            match_id,
            match_name,
            reason,
            main_market,
            main_odds,
            main_sum,
            hedge_market,
            hedge_odds,
            hedge_sum,
            json.dumps(pnl_data),
            json.dumps(raw_data) if raw_data else None
        ))
        
        conn.commit()
        conn.close()
        logger.info(f"Signal saved: {match_id} - {reason}")
    
    def get_signals(
        self,
        limit: int = 100,
        match_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get signals from journal"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if match_id:
            cursor.execute("""
                SELECT * FROM signals 
                WHERE match_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (match_id, limit))
        else:
            cursor.execute("""
                SELECT * FROM signals 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def export_csv(self, output_path: str) -> bool:
        """Export signals to CSV"""
        try:
            import csv
            signals = self.get_signals(limit=10000)
            
            if not signals:
                return False
            
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=signals[0].keys())
                writer.writeheader()
                writer.writerows(signals)
            
            logger.info(f"Exported {len(signals)} signals to {output_path}")
            return True
        except Exception as e:
            logger.error(f"CSV export error: {e}")
            return False



