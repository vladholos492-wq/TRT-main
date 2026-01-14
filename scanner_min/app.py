"""Main entry point for BetBoom scanner"""
import asyncio
import random
import sys
from datetime import datetime
from typing import List
from bb import BetBoomParser, MatchData, check_signal
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def format_sets_score(sets: List[tuple]) -> str:
    """Форматирование счёта по сетам"""
    if len(sets) >= 2:
        return f"{sets[0][0]}:{sets[0][1]}, {sets[1][0]}:{sets[1][1]}"
    return "-"


def format_odds(p1: float, p2: float) -> str:
    """Форматирование коэффициентов"""
    if p1 is not None and p2 is not None:
        return f"{p1:.2f},{p2:.2f}"
    return "-,-"


def print_table(matches: List[MatchData]):
    """Вывод таблицы матчей"""
    signals = [m for m in matches if check_signal(m)]
    
    print("\n" + "="*120)
    print(f"TIME: {datetime.now().strftime('%H:%M:%S')} | MATCHES: {len(matches)} | SIGNALS: {len(signals)}")
    print("="*120)
    
    if signals:
        print(f"{'TIME':<8} | {'MATCH_URL':<50} | {'SETS':<12} | {'GAME3':<8} | {'MATCH_ODDS':<15} | {'SET3_ODDS':<15} | SIGNAL")
        print("-"*120)
        
        for match in signals:
            time_str = match.last_update.strftime('%H:%M:%S')
            sets_str = format_sets_score(match.sets_score)
            game3_str = f"{match.set3_score[0]}:{match.set3_score[1]}"
            match_odds_str = format_odds(match.odds_p1, match.odds_p2)
            set3_odds_str = format_odds(match.set3_odds_p1, match.set3_odds_p2)
            
            # Определяем фаворита для вывода
            if match.odds_p1 and match.odds_p2:
                favorite = "P1" if match.odds_p1 < match.odds_p2 else "P2"
                favorite_odds = match.odds_p1 if match.odds_p1 < match.odds_p2 else match.odds_p2
                set3_favorite_odds = match.set3_odds_p1 if match.odds_p1 < match.odds_p2 else match.set3_odds_p2
                signal_str = f"OK ({favorite} {favorite_odds:.2f} -> {set3_favorite_odds:.2f})"
            else:
                signal_str = "OK"
            
            print(f"{time_str:<8} | {match.match_url:<50} | {sets_str:<12} | {game3_str:<8} | {match_odds_str:<15} | {set3_odds_str:<15} | {signal_str}")
        
        print("="*120)
    else:
        print(f"NO SIGNALS | Total matches scanned: {len(matches)}")
        if matches:
            print("Available matches:")
            for match in matches[:5]:  # Показываем первые 5 для отладки
                print(f"  - {match.match_name}: {format_odds(match.odds_p1, match.odds_p2)}")
        print("="*120)


async def main_loop():
    """Основной цикл сканирования"""
    parser = BetBoomParser()
    retry_count = 0
    max_retries = 3
    
    while True:
        try:
            # Запуск/перезапуск браузера
            if parser.page is None:
                logger.info("Starting browser...")
                if not await parser.start():
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error("Failed to start browser after multiple attempts")
                        break
                    await asyncio.sleep(5)
                    continue
                retry_count = 0
            
            # Обновление данных
            await parser.refresh()
            
            # Получение матчей
            matches = parser.get_matches()
            
            # Вывод результатов
            print_table(matches)
            
            # Случайная задержка 2-5 секунд
            delay = random.uniform(2, 5)
            await asyncio.sleep(delay)
            
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            retry_count += 1
            
            if retry_count >= max_retries:
                logger.error("Too many errors, restarting browser...")
                try:
                    await parser.stop()
                except Exception:
                    pass
                parser.page = None
                parser.context = None
                parser.browser = None
                retry_count = 0
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(2)


async def main():
    """Точка входа"""
    parser = None
    try:
        logger.info("BetBoom Live Scanner started")
        parser = BetBoomParser()
        await main_loop()
    except KeyboardInterrupt:
        logger.info("Scanner stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if parser:
            try:
                await parser.stop()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        