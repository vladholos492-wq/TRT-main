"""JSON and DOM extraction for match data"""

import re
from typing import Dict, Optional, Tuple, List
from app.util import normalize_odds
from app.config import LIVE_URL


def extract_match_from_json(item: Dict) -> Optional[Dict]:
    """Извлекает данные матча из JSON API ответа"""
    try:
        match_id = str(item.get('id') or item.get('match_id') or item.get('event_id', ''))
        if not match_id:
            return None
        
        # URL
        match_url = item.get('url') or item.get('link') or f"{LIVE_URL}#{match_id}"
        
        # Игроки
        home = item.get('home', {})
        away = item.get('away', {})
        if isinstance(home, str):
            home = {'name': home}
        if isinstance(away, str):
            away = {'name': away}
        if isinstance(home, dict):
            player1 = home.get('name', 'Unknown')
        else:
            player1 = 'Unknown'
        if isinstance(away, dict):
            player2 = away.get('name', 'Unknown')
        else:
            player2 = 'Unknown'
        
        match_name = item.get('name') or f"{player1} vs {player2}"
        
        # Лига
        league = None
        for key in ['league', 'tournament', 'competition', 'category']:
            if key in item:
                league_obj = item[key]
                if isinstance(league_obj, dict):
                    league = league_obj.get('name') or league_obj.get('title')
                else:
                    league = str(league_obj)
                break
        
        # Коэффициенты на матч
        odds = item.get('odds') or item.get('markets') or {}
        match_p1, match_p2 = extract_match_odds(odds)
        
        # Счёт
        score = item.get('score') or item.get('scores') or {}
        sets_score, set3_score = extract_score(score)
        
        # Коэффициенты на 3-й сет
        set3_p1, set3_p2 = extract_set3_odds(odds)
        
        return {
            'match_id': match_id,
            'match_url': match_url,
            'player1': player1,
            'player2': player2,
            'match_name': match_name,
            'league': league,
            'match_p1': match_p1,
            'match_p2': match_p2,
            'set3_p1': set3_p1,
            'set3_p2': set3_p2,
            'sets_score': sets_score,
            'set3_score': set3_score,
        }
    except Exception:
        return None


def extract_match_odds(odds_data) -> Tuple[Optional[float], Optional[float]]:
    """Извлекает коэффициенты на исход матча"""
    p1, p2 = None, None
    
    markets = []
    if isinstance(odds_data, dict):
        markets = odds_data.get('markets', [])
        if not markets:
            markets = [odds_data]
    elif isinstance(odds_data, list):
        markets = odds_data
    
    for market in markets:
        if not isinstance(market, dict):
            continue
        market_name = (market.get('name') or market.get('type') or '').lower()
        
        if 'исход' in market_name or 'match' in market_name or 'winner' in market_name:
            outcomes = market.get('outcomes') or market.get('selections') or []
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                name = (outcome.get('name') or outcome.get('label') or '').lower()
                odds_val = outcome.get('odds') or outcome.get('price') or outcome.get('value')
                
                odds_float = normalize_odds(odds_val)
                if odds_float is None:
                    continue
                
                if '1' in name or 'home' in name or 'п1' in name or 'first' in name:
                    p1 = odds_float
                elif '2' in name or 'away' in name or 'п2' in name or 'second' in name:
                    p2 = odds_float
    
    return p1, p2


def extract_set3_odds(odds_data) -> Tuple[Optional[float], Optional[float]]:
    """Извлекает коэффициенты на 3-й сет"""
    p1, p2 = None, None
    
    markets = []
    if isinstance(odds_data, dict):
        markets = odds_data.get('markets', [])
        if not markets:
            markets = [odds_data]
    elif isinstance(odds_data, list):
        markets = odds_data
    
    for market in markets:
        if not isinstance(market, dict):
            continue
        market_name = (market.get('name') or market.get('type') or '').lower()
        
        if ('3' in market_name and ('сет' in market_name or 'set' in market_name)) or 'set 3' in market_name:
            outcomes = market.get('outcomes') or market.get('selections') or []
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                name = (outcome.get('name') or outcome.get('label') or '').lower()
                odds_val = outcome.get('odds') or outcome.get('price') or outcome.get('value')
                
                odds_float = normalize_odds(odds_val)
                if odds_float is None:
                    continue
                
                if '1' in name or 'home' in name or 'п1' in name:
                    p1 = odds_float
                elif '2' in name or 'away' in name or 'п2' in name:
                    p2 = odds_float
    
    return p1, p2


def extract_score(score_data: Dict) -> Tuple[List[Tuple[int, int]], Tuple[int, int]]:
    """Извлекает счёт"""
    sets_score = []
    set3_score = (0, 0)
    
    if not isinstance(score_data, dict):
        return sets_score, set3_score
    
    # Сеты
    sets = score_data.get('sets') or score_data.get('periods') or []
    if isinstance(sets, list):
        for s in sets[:2]:
            if isinstance(s, dict):
                p1 = int(s.get('home', s.get('p1', s.get('score1', 0))))
                p2 = int(s.get('away', s.get('p2', s.get('score2', 0))))
                sets_score.append((p1, p2))
    
    # Текущий счёт 3-го сета
    current = score_data.get('current_score') or score_data.get('live_score') or {}
    if isinstance(current, dict):
        set3_score = (
            int(current.get('home', current.get('p1', current.get('score1', 0)))),
            int(current.get('away', current.get('p2', current.get('score2', 0))))
        )
    
    return sets_score, set3_score



