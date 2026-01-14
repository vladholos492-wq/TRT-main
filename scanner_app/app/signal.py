"""Signal detection logic and anti-spam"""

from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta
from app.config import MAX_MATCH_ODDS, MIN_SET3_ODDS, ALERT_COOLDOWN, ALERT_REPEAT_THRESHOLD


def check_signal(match_data: Dict) -> Tuple[bool, Optional[Dict]]:
    """Проверяет условия сигнала. Возвращает (is_signal, signal_info)"""
    # 1. Фаворит по матчу
    match_p1 = match_data.get('match_p1')
    match_p2 = match_data.get('match_p2')
    
    if match_p1 is None or match_p2 is None:
        return False, None
    
    favorite_odds = min(match_p1, match_p2)
    if favorite_odds > MAX_MATCH_ODDS:
        return False, None
    
    is_p1_favorite = match_p1 < match_p2
    favorite_side = "P1" if is_p1_favorite else "P2"
    
    # 2. Ведёт 2:0 по сетам
    sets_score = match_data.get('sets_score', [])
    if len(sets_score) < 2:
        return False, None
    
    set1, set2 = sets_score[0], sets_score[1]
    
    if is_p1_favorite:
        if not (set1[0] > set1[1] and set2[0] > set2[1]):
            return False, None
    else:
        if not (set1[1] > set1[0] and set2[1] > set2[0]):
            return False, None
    
    # 3. 3-й сет 0:0 или 1:0 или 0:1
    set3_p1, set3_p2 = match_data.get('set3_score', (0, 0))
    if not ((set3_p1 == 0 and set3_p2 == 0) or
            (set3_p1 == 1 and set3_p2 == 0) or
            (set3_p1 == 0 and set3_p2 == 1)):
        return False, None
    
    # 4. Кф на 3-й сет фаворита >= 1.90
    set3_p1_odds = match_data.get('set3_p1')
    set3_p2_odds = match_data.get('set3_p2')
    
    fav_set3_odds = set3_p1_odds if is_p1_favorite else set3_p2_odds
    if fav_set3_odds is None or fav_set3_odds < MIN_SET3_ODDS:
        return False, None
    
    # Формируем signal_info
    signal_info = {
        'match_id': match_data.get('match_id'),
        'match_url': match_data.get('match_url'),
        'player1': match_data.get('player1', 'Unknown'),
        'player2': match_data.get('player2', 'Unknown'),
        'league': match_data.get('league'),
        'favorite_side': favorite_side,
        'match_p1': match_p1,
        'match_p2': match_p2,
        'fav_match_odds': favorite_odds,
        'set3_p1': set3_p1_odds,
        'set3_p2': set3_p2_odds,
        'fav_set3_odds': fav_set3_odds,
        'sets_score': sets_score,
        'set3_score': (set3_p1, set3_p2),
    }
    
    return True, signal_info


def should_alert(storage_state: Dict, match_id: str, fav_set3_odds: float) -> bool:
    """Проверяет anti-spam: нужно ли показывать алерт"""
    cooldowns = storage_state.get('alert_cooldowns', {})
    
    if match_id not in cooldowns:
        return True
    
    last_alert = cooldowns[match_id]
    last_time = datetime.fromisoformat(last_alert.get('time', datetime.now().isoformat()))
    last_odds = last_alert.get('odds', 0.0)
    
    # Проверка cooldown
    if datetime.now() - last_time < timedelta(seconds=ALERT_COOLDOWN):
        # Но если кф вырос значительно - разрешаем повторный алерт
        if fav_set3_odds >= last_odds + ALERT_REPEAT_THRESHOLD:
            return True
        return False
    
    return True


def update_alert_cooldown(storage_state: Dict, match_id: str, fav_set3_odds: float):
    """Обновляет cooldown для алерта"""
    if 'alert_cooldowns' not in storage_state:
        storage_state['alert_cooldowns'] = {}
    
    storage_state['alert_cooldowns'][match_id] = {
        'time': datetime.now().isoformat(),
        'odds': fav_set3_odds
    }


def generate_signal_text(signal_info: Dict) -> str:
    """Генерирует текст сигнала для копирования"""
    player1 = signal_info.get('player1', 'Unknown')
    player2 = signal_info.get('player2', 'Unknown')
    league = signal_info.get('league', 'Unknown League')
    sets = ", ".join([f"{s[0]}:{s[1]}" for s in signal_info.get('sets_score', [])[:2]])
    game3 = f"{signal_info.get('set3_score', (0, 0))[0]}:{signal_info.get('set3_score', (0, 0))[1]}"
    fav_side = signal_info.get('favorite_side', 'P1')
    fav_match = signal_info.get('fav_match_odds', 0.0)
    fav_set3 = signal_info.get('fav_set3_odds', 0.0)
    url = signal_info.get('match_url', '')
    
    return (
        f"ЖЕЛЕЗОБЕТОННЫЙ ПЕРЕКОС: {player1} vs {player2} | Лига: {league}\n"
        f"Сеты: {sets} | 3-й сет: {game3}\n"
        f"Фаворит по матчу: {fav_side} (кф {fav_match:.2f})\n"
        f"В 3-м сете дают {fav_set3:.2f} — перекос цены. {url}"
    )



