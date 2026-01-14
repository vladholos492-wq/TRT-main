"""Main scanner that coordinates browser, network capture, and strategy"""
import asyncio
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from loguru import logger

from app.scanner.browser import BrowserManager
from app.engine.normalizer import EventNormalizer
from app.engine.strategy import TT_LIVE_V1_Strategy, Signal


class Scanner:
    """Main scanner coordinator"""
    
    def __init__(self):
        self.browser = BrowserManager()
        self.normalizer = EventNormalizer()
        self.strategy = TT_LIVE_V1_Strategy()
        self.is_running = False
        self.events: Dict[str, Dict[str, Any]] = {}  # match_id -> event
        self.signals: Dict[str, Signal] = {}  # match_id -> last signal
        self.signal_cooldown: Dict[str, datetime] = {}  # match_id -> last signal time
        self.cooldown_seconds = 180
        self.last_update_time: Optional[datetime] = None
        self.events_per_minute = 0
        self.event_count_window = []
        
        # Callbacks
        self.on_event_update: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_signal: Optional[Callable[[Signal], None]] = None
        self.on_status_change: Optional[Callable[[str], None]] = None
    
    async def start(self):
        """Start scanner"""
        if self.is_running:
            return
        
        try:
            # Start browser
            await self.browser.start()
            
            # Setup network callback
            self.browser.set_network_callback(self._handle_network_data)
            
            # Navigate to live page
            await self.browser.navigate_to_live()
            
            # Check if login required
            login_required = await self.browser.check_login_required()
            if login_required:
                logger.info("Login required - waiting for user to login...")
                if self.on_status_change:
                    self.on_status_change("waiting_login")
                # Wait for login (poll every 5 seconds)
                await self._wait_for_login()
            
            self.is_running = True
            self.last_update_time = datetime.now()
            
            if self.on_status_change:
                self.on_status_change("connected")
            
            logger.info("Scanner started")
            
            # Start monitoring loop
            asyncio.create_task(self._monitoring_loop())
            
        except Exception as e:
            logger.error(f"Failed to start scanner: {e}")
            if self.on_status_change:
                self.on_status_change("error")
            raise
    
    async def _wait_for_login(self, max_wait: int = 300):
        """Wait for user to login (max 5 minutes)"""
        waited = 0
        while waited < max_wait:
            await asyncio.sleep(5)
            waited += 5
            
            login_required = await self.browser.check_login_required()
            if not login_required:
                logger.info("Login detected - continuing scan")
                if self.on_status_change:
                    self.on_status_change("connected")
                return
        
        logger.warning("Login timeout - continuing anyway")
    
    async def _monitoring_loop(self):
        """Main monitoring loop"""
        while self.is_running:
            try:
                # Check for stale events (no update > 60 seconds)
                await self._check_stale_events()
                
                # Calculate events per minute
                await self._update_metrics()
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(5)
    
    async def _check_stale_events(self):
        """Mark events as stale if no update > 60 seconds"""
        now = datetime.now()
        stale_threshold = timedelta(seconds=60)
        
        for match_id, event in list(self.events.items()):
            last_update_ts = event.get('last_update_ts')
            if last_update_ts:
                try:
                    last_update = datetime.fromtimestamp(last_update_ts)
                    if now - last_update > stale_threshold:
                        event['_status'] = 'STALE'
                        if self.on_event_update:
                            self.on_event_update(event)
                except:
                    pass
    
    async def _update_metrics(self):
        """Update metrics (events/min, last update time)"""
        now = datetime.now()
        
        # Clean old events from window (keep last 60 seconds)
        cutoff = now - timedelta(seconds=60)
        self.event_count_window = [
            ts for ts in self.event_count_window
            if ts > cutoff
        ]
        
        self.events_per_minute = len(self.event_count_window)
        
        if self.on_status_change:
            self.on_status_change("connected")
    
    def _handle_network_data(self, data: Dict[str, Any]):
        """Handle network response data"""
        try:
            # Try different payload structures
            payload = data.get('data') or data.get('payload') or data
            
            if not payload:
                return
            
            # Normalize events from payload
            events = self.normalizer.normalize_events_list(payload)
            
            if not events:
                # Try single event
                event = self.normalizer.normalize_event(payload)
                if event:
                    events = [event]
            
            # Process each event
            for event in events:
                self._process_event(event)
                
        except Exception as e:
            logger.debug(f"Network data handling error: {e}")
            # Log full data for debugging
            logger.debug(f"Data keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
    
    def _process_event(self, event: Dict[str, Any]):
        """Process normalized event"""
        match_id = event.get('match_id')
        if not match_id:
            return
        
        # Update event timestamp
        event['last_update_ts'] = event.get('last_update_ts') or datetime.now().timestamp()
        event['_last_seen'] = datetime.now()
        
        # Determine status
        status = event.get('status', 'unknown')
        if status == 'live':
            event['_status'] = 'WATCH'
        elif status == 'finished':
            event['_status'] = 'FINISHED'
        else:
            event['_status'] = 'WATCH'
        
        # Store event
        self.events[match_id] = event
        
        # Update metrics
        self.event_count_window.append(datetime.now())
        self.last_update_time = datetime.now()
        
        # Check strategy
        signal = self.strategy.check_signal(event)
        
        if signal:
            # Check cooldown
            if self._check_cooldown(match_id, signal.reason):
                signal.reason = f"{signal.reason} (cooldown)"
                event['_status'] = 'CANDIDATE'
            else:
                # New signal!
                self.signals[match_id] = signal
                self.signal_cooldown[match_id] = datetime.now()
                event['_status'] = 'SIGNAL'
                
                if self.on_signal:
                    self.on_signal(signal)
                
                logger.info(f"Signal detected: {match_id} - {signal.reason}")
        else:
            # Check if it's a candidate (close to signal but not quite)
            if self._is_candidate(event):
                event['_status'] = 'CANDIDATE'
        
        # Notify UI
        if self.on_event_update:
            self.on_event_update(event)
    
    def _check_cooldown(self, match_id: str, reason: str) -> bool:
        """Check if signal is in cooldown period"""
        if match_id not in self.signal_cooldown:
            return False
        
        last_signal_time = self.signal_cooldown[match_id]
        elapsed = (datetime.now() - last_signal_time).total_seconds()
        
        if elapsed < self.cooldown_seconds:
            # Check if reason changed (if changed, allow new signal)
            if match_id in self.signals:
                old_reason = self.signals[match_id].reason
                if reason != old_reason:
                    return False  # Reason changed, allow signal
            return True  # Still in cooldown
        
        return False
    
    def _is_candidate(self, event: Dict[str, Any]) -> bool:
        """Check if event is close to triggering signal (candidate)"""
        # Simple heuristic: if diff is close to threshold
        try:
            score_points = event.get('score_points_current_set')
            if not score_points:
                return False
            
            p1_str, p2_str = score_points.split(':')
            p1 = int(p1_str.strip())
            p2 = int(p2_str.strip())
            diff = abs(p1 - p2)
            
            # Candidate if diff is 1-5 (close to signal range 2-4)
            return 1 <= diff <= 5
        except:
            return False
    
    def get_active_matches_count(self) -> int:
        """Get count of active (non-stale) matches"""
        now = datetime.now()
        count = 0
        
        for event in self.events.values():
            status = event.get('_status', '')
            if status not in ['STALE', 'FINISHED']:
                count += 1
        
        return count
    
    def get_events(self) -> Dict[str, Dict[str, Any]]:
        """Get all events"""
        return self.events.copy()
    
    def get_last_signal(self) -> Optional[Signal]:
        """Get most recent signal"""
        if not self.signals:
            return None
        
        # Return signal with most recent timestamp
        latest = None
        latest_time = None
        
        for match_id, signal in self.signals.items():
            if match_id in self.signal_cooldown:
                signal_time = self.signal_cooldown[match_id]
                if latest_time is None or signal_time > latest_time:
                    latest = signal
                    latest_time = signal_time
        
        return latest
    
    async def stop(self):
        """Stop scanner"""
        self.is_running = False
        await self.browser.stop()
        logger.info("Scanner stopped")
    
    async def reconnect(self):
        """Reconnect scanner"""
        logger.info("Reconnecting scanner...")
        try:
            await self.browser.reconnect()
            await self.browser.navigate_to_live()
            self.is_running = True
            if self.on_status_change:
                self.on_status_change("connected")
            logger.info("Scanner reconnected successfully")
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")
            if self.on_status_change:
                self.on_status_change("error")
            # Retry after delay
            await asyncio.sleep(5)
            await self.reconnect()

