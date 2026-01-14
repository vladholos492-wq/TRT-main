"""Universal adapter for normalizing different payload structures"""
from typing import Dict, Any, List, Optional
from loguru import logger


class EventNormalizer:
    """Adaptive parser that extracts event data from various payload structures"""
    
    @staticmethod
    def normalize_event(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract normalized event from payload.
        Returns None if event cannot be extracted.
        """
        try:
            # Try different common structures
            event = None
            
            # Structure 1: direct event object
            if isinstance(payload, dict) and 'id' in payload:
                event = payload
            
            # Structure 2: events array
            elif isinstance(payload, dict) and 'events' in payload:
                # Process first event or return None (will be called per event)
                events = payload.get('events', [])
                if events and isinstance(events, list):
                    event = events[0]
            
            # Structure 3: data.events
            elif isinstance(payload, dict) and 'data' in payload:
                data = payload.get('data', {})
                if isinstance(data, dict) and 'events' in data:
                    events = data.get('events', [])
                    if events and isinstance(events, list):
                        event = events[0]
            
            if not event or not isinstance(event, dict):
                return None
            
            # Extract normalized fields
            normalized = {
                'match_id': EventNormalizer._extract_match_id(event),
                'players': EventNormalizer._extract_players(event),
                'league': EventNormalizer._extract_league(event),
                'tour': EventNormalizer._extract_tour(event),
                'status': EventNormalizer._extract_status(event),
                'score_sets': EventNormalizer._extract_score_sets(event),
                'score_points_current_set': EventNormalizer._extract_score_points_current_set(event),
                'current_set_index': EventNormalizer._extract_current_set_index(event),
                'odds': EventNormalizer._extract_odds(event),
                'last_update_ts': EventNormalizer._extract_last_update_ts(event),
            }
            
            return normalized
            
        except Exception as e:
            logger.debug(f"Normalization error: {e}")
            return None
    
    @staticmethod
    def _extract_match_id(event: Dict[str, Any]) -> str:
        """Extract match ID"""
        for key in ['id', 'matchId', 'match_id', 'eventId', 'event_id']:
            if key in event:
                return str(event[key])
        return str(event.get('_id', 'unknown'))
    
    @staticmethod
    def _extract_players(event: Dict[str, Any]) -> Dict[str, str]:
        """Extract player names"""
        p1, p2 = None, None
        
        # Try different structures
        if 'players' in event and isinstance(event['players'], list):
            players = event['players']
            if len(players) >= 2:
                p1 = str(players[0].get('name', players[0].get('title', '')))
                p2 = str(players[1].get('name', players[1].get('title', '')))
        
        if 'competitors' in event and isinstance(event['competitors'], list):
            competitors = event['competitors']
            if len(competitors) >= 2:
                p1 = str(competitors[0].get('name', competitors[0].get('title', '')))
                p2 = str(competitors[1].get('name', competitors[1].get('title', '')))
        
        if 'home' in event and 'away' in event:
            p1 = str(event['home'].get('name', event['home'].get('title', '')))
            p2 = str(event['away'].get('name', event['away'].get('title', '')))
        
        if 'p1' in event:
            p1 = str(event['p1'])
        if 'p2' in event:
            p2 = str(event['p2'])
        
        return {'p1': p1 or 'Player 1', 'p2': p2 or 'Player 2'}
    
    @staticmethod
    def _extract_league(event: Dict[str, Any]) -> Optional[str]:
        """Extract league/tournament name"""
        for key in ['league', 'tournament', 'competition', 'category']:
            if key in event:
                league = event[key]
                if isinstance(league, dict):
                    return league.get('name', league.get('title'))
                return str(league)
        return None
    
    @staticmethod
    def _extract_tour(event: Dict[str, Any]) -> Optional[str]:
        """Extract tour name"""
        if 'tour' in event:
            return str(event['tour'])
        return None
    
    @staticmethod
    def _extract_status(event: Dict[str, Any]) -> str:
        """Extract match status"""
        status = event.get('status', event.get('state', 'unknown'))
        status_str = str(status).lower()
        
        if 'live' in status_str or status_str == '1':
            return 'live'
        elif 'paused' in status_str or status_str == '2':
            return 'paused'
        elif 'finished' in status_str or status_str == '3':
            return 'finished'
        return 'unknown'
    
    @staticmethod
    def _extract_score_sets(event: Dict[str, Any]) -> Optional[str]:
        """Extract sets score (e.g., '1:0')"""
        # Try different structures
        if 'score' in event:
            score = event['score']
            if isinstance(score, dict):
                sets_p1 = score.get('sets1', score.get('sets_p1', 0))
                sets_p2 = score.get('sets2', score.get('sets_p2', 0))
                return f"{sets_p1}:{sets_p2}"
            elif isinstance(score, str):
                return score
        
        if 'sets' in event:
            sets = event['sets']
            if isinstance(sets, dict):
                return f"{sets.get('p1', 0)}:{sets.get('p2', 0)}"
        
        return None
    
    @staticmethod
    def _extract_score_points_current_set(event: Dict[str, Any]) -> Optional[str]:
        """Extract current set points (e.g., '6:4')"""
        if 'currentSet' in event:
            cs = event['currentSet']
            if isinstance(cs, dict):
                return f"{cs.get('p1', 0)}:{cs.get('p2', 0)}"
        
        if 'current_set' in event:
            cs = event['current_set']
            if isinstance(cs, dict):
                return f"{cs.get('points1', cs.get('p1', 0))}:{cs.get('points2', cs.get('p2', 0))}"
        
        if 'score' in event:
            score = event['score']
            if isinstance(score, dict) and 'current' in score:
                curr = score['current']
                if isinstance(curr, dict):
                    return f"{curr.get('p1', 0)}:{curr.get('p2', 0)}"
        
        return None
    
    @staticmethod
    def _extract_current_set_index(event: Dict[str, Any]) -> Optional[int]:
        """Extract current set number (1-based)"""
        for key in ['currentSetIndex', 'current_set_index', 'setNumber', 'set_number']:
            if key in event:
                val = event[key]
                if isinstance(val, (int, float)):
                    return int(val)
        return None
    
    @staticmethod
    def _extract_odds(event: Dict[str, Any]) -> Dict[str, Any]:
        """Extract odds for various markets"""
        odds = {}
        
        # Try to find markets/odds structure
        markets = event.get('markets', event.get('odds', {}))
        if not isinstance(markets, dict) and isinstance(markets, list):
            # Convert list to dict by market type
            markets_dict = {}
            for m in markets:
                if isinstance(m, dict):
                    mtype = m.get('type', m.get('name'))
                    if mtype:
                        markets_dict[mtype] = m
            markets = markets_dict
        
        if isinstance(markets, dict):
            # Match winner
            if 'match_winner' in markets:
                mw = markets['match_winner']
                if isinstance(mw, dict):
                    odds['match_winner'] = {
                        'p1': mw.get('p1', mw.get('home')),
                        'p2': mw.get('p2', mw.get('away'))
                    }
            
            # Set winner
            if 'set_winner' in markets or 'current_set_winner' in markets:
                sw = markets.get('set_winner') or markets.get('current_set_winner')
                if isinstance(sw, dict):
                    odds['set_winner_current'] = {
                        'p1': sw.get('p1', sw.get('home')),
                        'p2': sw.get('p2', sw.get('away'))
                    }
            
            # Handicap current set
            if 'handicap_current_set' in markets:
                hcs = markets['handicap_current_set']
                if isinstance(hcs, dict):
                    odds['handicap_current_set'] = hcs
            
            # Total points current set
            if 'total_points_current_set' in markets or 'total_current_set' in markets:
                tcs = markets.get('total_points_current_set') or markets.get('total_current_set')
                if isinstance(tcs, dict):
                    odds['total_points_current_set'] = tcs
        
        return odds
    
    @staticmethod
    def _extract_last_update_ts(event: Dict[str, Any]) -> Optional[float]:
        """Extract last update timestamp"""
        for key in ['lastUpdate', 'last_update', 'updatedAt', 'updated_at', 'timestamp']:
            if key in event:
                val = event[key]
                if isinstance(val, (int, float)):
                    return float(val)
                elif isinstance(val, str):
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(val.replace('Z', '+00:00'))
                        return dt.timestamp()
                    except:
                        pass
        return None
    
    @staticmethod
    def normalize_events_list(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract list of normalized events from payload"""
        events = []
        
        # Try to find events array
        events_list = None
        
        if isinstance(payload, list):
            events_list = payload
        elif isinstance(payload, dict):
            if 'events' in payload:
                events_list = payload['events']
            elif 'data' in payload and isinstance(payload['data'], dict):
                if 'events' in payload['data']:
                    events_list = payload['data']['events']
        
        if events_list and isinstance(events_list, list):
            for event in events_list:
                normalized = EventNormalizer.normalize_event(event)
                if normalized:
                    events.append(normalized)
        
        return events



