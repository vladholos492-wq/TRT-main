"""Storage for signals (CSV + SQLite) and state"""

import sqlite3
import csv
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
from app.config import APP_DATA_DIR, SIGNALS_CSV, SIGNALS_DB, STATE_JSON


class Storage:
    """Manages signal storage and state"""
    
    def __init__(self):
        self.data_dir = Path(APP_DATA_DIR)
        self.data_dir.mkdir(exist_ok=True)
        
        self.csv_path = self.data_dir / SIGNALS_CSV
        self.db_path = self.data_dir / SIGNALS_DB
        self.state_path = self.data_dir / STATE_JSON
        
        self._init_csv()
        self._init_db()
        self.state = self._load_state()
    
    def _init_csv(self):
        """Initialize CSV file"""
        if not self.csv_path.exists():
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'ts', 'players', 'league', 'url', 'sets', 'game3',
                    'match_p1', 'match_p2', 'fav_side', 'fav_match',
                    'set3_p1', 'set3_p2', 'fav_set3', 'reason', 'app_version'
                ])
    
    def _init_db(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                players TEXT NOT NULL,
                league TEXT,
                url TEXT NOT NULL,
                sets TEXT NOT NULL,
                game3 TEXT NOT NULL,
                match_p1 REAL,
                match_p2 REAL,
                fav_side TEXT NOT NULL,
                fav_match REAL NOT NULL,
                set3_p1 REAL,
                set3_p2 REAL,
                fav_set3 REAL NOT NULL,
                reason TEXT,
                app_version TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def _load_state(self) -> Dict:
        """Load state from JSON"""
        if self.state_path.exists():
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {"alert_cooldowns": {}, "match_cache": {}}
    
    def save_state(self):
        """Save state to JSON"""
        try:
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    def save_signal(self, signal_data: Dict):
        """Save signal to CSV and SQLite"""
        from app import __version__
        
        # CSV
        with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                signal_data.get('ts', datetime.now().isoformat()),
                signal_data.get('players', ''),
                signal_data.get('league', ''),
                signal_data.get('url', ''),
                signal_data.get('sets', ''),
                signal_data.get('game3', ''),
                signal_data.get('match_p1'),
                signal_data.get('match_p2'),
                signal_data.get('fav_side', ''),
                signal_data.get('fav_match'),
                signal_data.get('set3_p1'),
                signal_data.get('set3_p2'),
                signal_data.get('fav_set3'),
                signal_data.get('reason', ''),
                __version__
            ])
        
        # SQLite
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO signals 
            (ts, players, league, url, sets, game3,
             match_p1, match_p2, fav_side, fav_match,
             set3_p1, set3_p2, fav_set3, reason, app_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal_data.get('ts', datetime.now().isoformat()),
            signal_data.get('players', ''),
            signal_data.get('league', ''),
            signal_data.get('url', ''),
            signal_data.get('sets', ''),
            signal_data.get('game3', ''),
            signal_data.get('match_p1'),
            signal_data.get('match_p2'),
            signal_data.get('fav_side', ''),
            signal_data.get('fav_match'),
            signal_data.get('set3_p1'),
            signal_data.get('set3_p2'),
            signal_data.get('fav_set3'),
            signal_data.get('reason', ''),
            __version__
        ))
        
        conn.commit()
        conn.close()
    
    def get_today_signals_count(self) -> int:
        """Get count of signals today"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        today = datetime.now().date().isoformat()
        cursor.execute('SELECT COUNT(*) FROM signals WHERE DATE(ts) = ?', (today,))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count



