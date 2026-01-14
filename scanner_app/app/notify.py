"""Notifications (sound + Windows toast)"""

import winsound
import pyperclip
import webbrowser
from typing import Dict

try:
    from winotify import Notification
    WINOTIFY_AVAILABLE = True
except ImportError:
    WINOTIFY_AVAILABLE = False


def play_alert_sound():
    """Воспроизводит звуковой сигнал"""
    try:
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        winsound.Beep(800, 200)
        winsound.Beep(1000, 200)
    except Exception:
        pass


def show_toast(signal_info: Dict):
    """Показывает Windows toast уведомление"""
    if not WINOTIFY_AVAILABLE:
        return
    
    try:
        player1 = signal_info.get('player1', 'Unknown')
        player2 = signal_info.get('player2', 'Unknown')
        fav_set3 = signal_info.get('fav_set3_odds', 0.0)
        
        toast = Notification(
            app_id="BB Hacker Scanner",
            title="🎾 IRON BET FOUND",
            msg=f"{player1} vs {player2}\n"
                f"BET: Fav wins Set 3 @ {fav_set3:.2f}",
            duration="long"
        )
        toast.show()
    except Exception:
        pass


def copy_to_clipboard(text: str) -> bool:
    """Копирует текст в буфер обмена"""
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def open_match_url(url: str):
    """Открывает URL матча в браузере"""
    try:
        webbrowser.open(url)
    except Exception:
        pass


def notify_signal(signal_info: Dict):
    """Уведомляет о сигнале (звук + toast)"""
    play_alert_sound()
    show_toast(signal_info)



