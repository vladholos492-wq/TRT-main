"""Utility functions"""

import re
from typing import Optional


def normalize_odds(value) -> Optional[float]:
    """Нормализует коэффициент: '1,63' -> 1.63, '—' -> None"""
    if value is None:
        return None
    
    if isinstance(value, (int, float)):
        return float(value)
    
    value_str = str(value).strip().replace(',', '.')
    
    # Убираем лишние символы
    value_str = re.sub(r'[^\d.]', '', value_str)
    
    if not value_str or value_str in ['—', '-', '/']:
        return None
    
    try:
        return float(value_str)
    except (ValueError, TypeError):
        return None


def format_players(player1: str, player2: str) -> str:
    """Форматирует имена игроков"""
    p1 = player1 or "Unknown"
    p2 = player2 or "Unknown"
    return f"{p1} vs {p2}"


def format_sets_score(sets: list) -> str:
    """Форматирует счёт по сетам: [(2, 0), (3, 1)] -> '2:0, 3:1'"""
    if not sets or len(sets) < 2:
        return "-"
    return ", ".join([f"{s[0]}:{s[1]}" for s in sets[:2]])


def format_odds_pair(p1: Optional[float], p2: Optional[float]) -> str:
    """Форматирует пару коэффициентов"""
    if p1 is not None and p2 is not None:
        return f"{p1:.2f}/{p2:.2f}"
    return "-/-"



