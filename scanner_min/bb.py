"""BetBoom live table tennis parser"""
import asyncio
import json
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LIVE_URL = "https://betboom.ru/sport/table-tennis?period=all&type=live"


@dataclass
class MatchData:
    """Данные матча"""
    match_id: str
    match_url: str
    match_name: str = ""
    odds_p1: Optional[float] = None
    odds_p2: Optional[float] = None
    set3_odds_p1: Optional[float] = None
    set3_odds_p2: Optional[float] = None
    sets_score: List[Tuple[int, int]] = None  # [(p1, p2), (p1, p2)]
    set3_score: Tuple[int, int] = (0, 0)  # (p1, p2)
    last_update: datetime = None
    
    def __post_init__(self):
        if self.sets_score is None:
            self.sets_score = []
        if self.last_update is None:
            self.last_update = datetime.now()


class BetBoomParser:
    """Парсер BetBoom live матчей"""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.matches: Dict[str, MatchData] = {}
        self.api_responses: List[dict] = []
    
    async def start(self):
        """Запуск браузера"""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled']
            )
            self.context = await self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            self.page = await self.context.new_page()
            
            # Network interception
            self.page.on("response", self._handle_response)
            
            # Navigate to live page
            await self.page.goto(LIVE_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            
            logger.info("Browser started")
            return True
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            return False
    
    async def stop(self):
        """Остановка браузера"""
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
    
    async def _handle_response(self, response):
        """Обработка сетевых ответов"""
        try:
            url = response.url
            content_type = response.headers.get("content-type", "")
            
            if "application/json" in content_type or "json" in url.lower():
                try:
                    data = await response.json()
                    self.api_responses.append(data)
                    await self._parse_api_response(data, url)
                except Exception:
                    pass
        except Exception:
            pass
    
    async def _parse_api_response(self, data: dict, url: str):
        """Парсинг API ответа"""
        try:
            # Ищем массив матчей
            matches_list = None
            
            if isinstance(data, dict):
                for key in ['data', 'matches', 'events', 'results', 'items', 'events_data']:
                    if key in data and isinstance(data[key], list):
                        matches_list = data[key]
                        break
            elif isinstance(data, list):
                matches_list = data
            
            if matches_list:
                for item in matches_list:
                    await self._parse_match_item(item)
        except Exception as e:
            logger.debug(f"Error parsing API: {e}")
    
    async def _parse_match_item(self, item: dict):
        """Парсинг одного матча из API"""
        try:
            match_id = str(item.get('id') or item.get('match_id') or item.get('event_id', ''))
            if not match_id:
                return
            
            # URL матча
            match_url = item.get('url') or item.get('link') or f"{LIVE_URL}#{match_id}"
            
            # Название
            home = item.get('home', {})
            away = item.get('away', {})
            if isinstance(home, str):
                home = {'name': home}
            if isinstance(away, str):
                away = {'name': away}
            if isinstance(home, dict):
                home_name = home.get('name', 'Team1')
            else:
                home_name = 'Team1'
            if isinstance(away, dict):
                away_name = away.get('name', 'Team2')
            else:
                away_name = 'Team2'
            match_name = item.get('name') or f"{home_name} vs {away_name}"
            
            # Коэффициенты на исход матча
            odds = item.get('odds') or item.get('markets') or {}
            match_odds_p1, match_odds_p2 = self._extract_match_odds(odds)
            
            # Счёт
            score = item.get('score') or item.get('scores') or {}
            sets_score, set3_score = self._extract_score(score)
            
            # Коэффициенты на 3-й сет
            set3_odds_p1, set3_odds_p2 = self._extract_set3_odds(odds)
            
            # Сохраняем/обновляем матч
            if match_id in self.matches:
                match = self.matches[match_id]
                match.match_name = match_name
                match.match_url = match_url
                match.odds_p1 = match_odds_p1
                match.odds_p2 = match_odds_p2
                match.set3_odds_p1 = set3_odds_p1
                match.set3_odds_p2 = set3_odds_p2
                match.sets_score = sets_score
                match.set3_score = set3_score
                match.last_update = datetime.now()
            else:
                match = MatchData(
                    match_id=match_id,
                    match_url=match_url,
                    match_name=match_name,
                    odds_p1=match_odds_p1,
                    odds_p2=match_odds_p2,
                    set3_odds_p1=set3_odds_p1,
                    set3_odds_p2=set3_odds_p2,
                    sets_score=sets_score,
                    set3_score=set3_score
                )
                self.matches[match_id] = match
                
        except Exception as e:
            logger.debug(f"Error parsing match item: {e}")
    
    def _extract_match_odds(self, odds_data) -> Tuple[Optional[float], Optional[float]]:
        """Извлечение коэффициентов на исход матча"""
        p1, p2 = None, None
        
        # Нормализация структуры
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
            
            # Ищем рынок "Исход матча"
            if 'исход' in market_name or 'match' in market_name or 'winner' in market_name:
                outcomes = market.get('outcomes') or market.get('selections') or []
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    name = (outcome.get('name') or outcome.get('label') or '').lower()
                    odds_val = outcome.get('odds') or outcome.get('price') or outcome.get('value')
                    
                    if odds_val:
                        try:
                            odds_str = str(odds_val).replace(',', '.')
                            odds_float = float(re.search(r'\d+\.?\d*', odds_str).group())
                            
                            if '1' in name or 'home' in name or 'п1' in name or 'first' in name:
                                p1 = odds_float
                            elif '2' in name or 'away' in name or 'п2' in name or 'second' in name:
                                p2 = odds_float
                        except (ValueError, TypeError, AttributeError):
                            pass
        
        return p1, p2
    
    def _extract_set3_odds(self, odds_data) -> Tuple[Optional[float], Optional[float]]:
        """Извлечение коэффициентов на 3-й сет"""
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
            
            # Ищем рынок "3-й сет"
            if ('3' in market_name and ('сет' in market_name or 'set' in market_name)) or 'set 3' in market_name:
                outcomes = market.get('outcomes') or market.get('selections') or []
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    name = (outcome.get('name') or outcome.get('label') or '').lower()
                    odds_val = outcome.get('odds') or outcome.get('price') or outcome.get('value')
                    
                    if odds_val:
                        try:
                            odds_str = str(odds_val).replace(',', '.')
                            odds_float = float(re.search(r'\d+\.?\d*', odds_str).group())
                            
                            if '1' in name or 'home' in name or 'п1' in name:
                                p1 = odds_float
                            elif '2' in name or 'away' in name or 'п2' in name:
                                p2 = odds_float
                        except (ValueError, TypeError, AttributeError):
                            pass
        
        return p1, p2
    
    def _extract_score(self, score_data: dict) -> Tuple[List[Tuple[int, int]], Tuple[int, int]]:
        """Извлечение счёта"""
        sets_score = []
        set3_score = (0, 0)
        
        if not isinstance(score_data, dict):
            return sets_score, set3_score
        
        # Сеты
        sets = score_data.get('sets') or score_data.get('periods') or []
        if isinstance(sets, list):
            for s in sets[:2]:  # Первые 2 сета
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
    
    async def parse_dom_fallback(self):
        """Fallback: парсинг из DOM"""
        try:
            if not self.page:
                return
            
            # Попытка найти матчи в DOM
            # Это упрощённая версия - реальная структура DOM может отличаться
            match_elements = await self.page.query_selector_all(
                '[data-match-id], [data-event-id], .match-card, .event-card, [class*="match"]'
            )
            
            for elem in match_elements[:30]:
                try:
                    match_id = (
                        await elem.get_attribute('data-match-id') or
                        await elem.get_attribute('data-event-id') or
                        f"dom_{hash(str(elem))}"
                    )
                    
                    # Извлечение данных из текста элемента
                    text = await elem.inner_text()
                    
                    # Попытка найти коэффициенты и счёт в тексте
                    # Это базовая версия - можно улучшить
                    
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"DOM fallback error: {e}")
    
    async def refresh(self):
        """Обновление данных"""
        try:
            if self.page:
                # Пробуем обновить страницу
                await self.page.reload(wait_until="networkidle", timeout=30000)
                await asyncio.sleep(1)
                
                # Если API не дал данных, пробуем DOM
                if len(self.matches) == 0:
                    await self.parse_dom_fallback()
        except Exception as e:
            logger.debug(f"Refresh error: {e}")
    
    def get_matches(self) -> List[MatchData]:
        """Получить список матчей"""
        return list(self.matches.values())


def check_signal(match: MatchData) -> bool:
    """Проверка условий сигнала"""
    # 1. Фаворит (min(P1, P2) <= 1.20)
    if match.odds_p1 is None or match.odds_p2 is None:
        return False
    
    favorite_odds = min(match.odds_p1, match.odds_p2)
    if favorite_odds > 1.20:
        return False
    
    is_p1_favorite = match.odds_p1 < match.odds_p2
    
    # 2. Ведёт 2:0 по сетам
    if len(match.sets_score) < 2:
        return False
    
    set1, set2 = match.sets_score[0], match.sets_score[1]
    
    if is_p1_favorite:
        if not (set1[0] > set1[1] and set2[0] > set2[1]):
            return False
    else:
        if not (set1[1] > set1[0] and set2[1] > set2[0]):
            return False
    
    # 3. 3-й сет 0:0 или 1:0 или 0:1
    s3_p1, s3_p2 = match.set3_score
    if not ((s3_p1 == 0 and s3_p2 == 0) or
            (s3_p1 == 1 and s3_p2 == 0) or
            (s3_p1 == 0 and s3_p2 == 1)):
        return False
    
    # 4. Кф на 3-й сет фаворита >= 1.90
    set3_odds = match.set3_odds_p1 if is_p1_favorite else match.set3_odds_p2
    if set3_odds is None or set3_odds < 1.90:
        return False
    
    return True

