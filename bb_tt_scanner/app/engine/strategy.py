"""TT_LIVE_V1 strategy implementation"""
from typing import Dict, Any, Optional, Tuple
from loguru import logger
from dataclasses import dataclass


@dataclass
class StrategyConfig:
    """Strategy configuration"""
    min_diff: int = 2  # Minimum points difference for reversal
    max_diff: int = 4  # Maximum points difference for reversal
    momentum_ticks: int = 3  # Number of ticks to check momentum
    momentum_improvement: int = 2  # Minimum improvement in diff
    odds_min: float = 1.70
    odds_max: float = 2.60
    hedge_odds_min: float = 1.35
    hedge_odds_max: float = 1.80
    min_points_for_total: int = 12  # Minimum total points for hedge total
    min_score_for_total: int = 6  # Minimum score (6:6) for hedge total
    unit: float = 30.0  # Base unit in rubles
    max_units_per_match: int = 3  # Maximum units per match


@dataclass
class Signal:
    """Signal data structure"""
    match_id: str
    match_name: str
    reason: str
    main_market: str
    main_odds: float
    main_sum: float
    hedge_market: Optional[str]
    hedge_odds: Optional[float]
    hedge_sum: Optional[float]
    pnl_data: Dict[str, Any]
    raw_event: Dict[str, Any]


class TT_LIVE_V1_Strategy:
    """TT_LIVE_V1 strategy: REVERSAL_NOT_END with MAIN + HEDGE"""
    
    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()
        self.match_history: Dict[str, list] = {}  # match_id -> list of events
    
    def is_not_end_of_set(self, event: Dict[str, Any]) -> bool:
        """
        Check if current set is NOT at the end.
        Rule: max(points_p1, points_p2) <= 8
        """
        score_points = event.get('score_points_current_set')
        if not score_points:
            return False
        
        try:
            # Parse "6:4" format
            p1_str, p2_str = score_points.split(':')
            p1 = int(p1_str.strip())
            p2 = int(p2_str.strip())
            max_points = max(p1, p2)
            return max_points <= 8
        except:
            return False
    
    def get_current_diff(self, event: Dict[str, Any]) -> Optional[Tuple[int, str]]:
        """
        Get current points difference in current set.
        Returns (diff, leading_player) or None
        """
        score_points = event.get('score_points_current_set')
        if not score_points:
            return None
        
        try:
            p1_str, p2_str = score_points.split(':')
            p1 = int(p1_str.strip())
            p2 = int(p2_str.strip())
            diff = abs(p1 - p2)
            
            if p1 > p2:
                return (diff, 'p1')
            elif p2 > p1:
                return (diff, 'p2')
            else:
                return (0, 'equal')
        except:
            return None
    
    def check_momentum(self, match_id: str, current_diff: int, leading_player: str) -> bool:
        """
        Check if momentum improved in last N ticks.
        Improvement: diff decreased by at least config.momentum_improvement
        """
        history = self.match_history.get(match_id, [])
        if len(history) < self.config.momentum_ticks:
            return False
        
        # Get last N events
        recent = history[-self.config.momentum_ticks:]
        
        # Find previous diff for the same leading player
        for prev_event in reversed(recent):
            prev_diff_data = self.get_current_diff(prev_event)
            if prev_diff_data:
                prev_diff, prev_leader = prev_diff_data
                if prev_leader == leading_player:
                    # Check if diff improved (decreased) by at least momentum_improvement
                    improvement = prev_diff - current_diff
                    return improvement >= self.config.momentum_improvement
        
        return False
    
    def find_main_market(self, event: Dict[str, Any], target_player: str) -> Optional[Tuple[str, float]]:
        """
        Find MAIN market for target player.
        Prefer: "Победа в текущем сете" -> "Победа в матче"
        Returns (market_name, odds) or None
        """
        odds = event.get('odds', {})
        
        # Try set winner current
        set_winner = odds.get('set_winner_current', {})
        if set_winner and target_player in set_winner:
            odds_val = set_winner[target_player]
            if isinstance(odds_val, (int, float)):
                kf = float(odds_val)
                if self.config.odds_min <= kf <= self.config.odds_max:
                    return ("Победа в текущем сете", kf)
        
        # Try match winner
        match_winner = odds.get('match_winner', {})
        if match_winner and target_player in match_winner:
            odds_val = match_winner[target_player]
            if isinstance(odds_val, (int, float)):
                kf = float(odds_val)
                if self.config.odds_min <= kf <= self.config.odds_max:
                    return ("Победа в матче", kf)
        
        return None
    
    def find_hedge_market(self, event: Dict[str, Any], target_player: str) -> Optional[Tuple[str, float]]:
        """
        Find HEDGE market.
        Prefer1: "Фора по очкам в текущем сете +X.5/+Y.5" на target_player
        Prefer2: "Тотал очков в текущем сете Больше" (if score >= 6:6 or total >= 12)
        Returns (market_name, odds) or None
        """
        odds = event.get('odds', {})
        score_points = event.get('score_points_current_set')
        
        # Parse current score
        p1, p2 = 0, 0
        if score_points:
            try:
                p1_str, p2_str = score_points.split(':')
                p1 = int(p1_str.strip())
                p2 = int(p2_str.strip())
            except:
                pass
        
        total_points = p1 + p2
        
        # Prefer1: Handicap current set
        handicap = odds.get('handicap_current_set', {})
        if handicap and isinstance(handicap, dict):
            # Look for handicap on target_player
            for key, value in handicap.items():
                if target_player in key.lower() or 'p1' in key.lower() and target_player == 'p1' or 'p2' in key.lower() and target_player == 'p2':
                    if isinstance(value, (int, float)):
                        kf = float(value)
                        if self.config.hedge_odds_min <= kf <= self.config.hedge_odds_max:
                            return (f"Фора по очкам в текущем сете {key}", kf)
        
        # Prefer2: Total points current set (only if score >= 6:6 or total >= 12)
        if (p1 >= self.config.min_score_for_total and p2 >= self.config.min_score_for_total) or total_points >= self.config.min_points_for_total:
            total_market = odds.get('total_points_current_set', {})
            if total_market and isinstance(total_market, dict):
                # Look for "Больше" (Over)
                for key, value in total_market.items():
                    if 'больше' in key.lower() or 'over' in key.lower() or '>' in key:
                        if isinstance(value, (int, float)):
                            kf = float(value)
                            if self.config.hedge_odds_min <= kf <= self.config.hedge_odds_max:
                                return ("Тотал очков в текущем сете Больше", kf)
        
        return None
    
    def calculate_sums(self, has_hedge: bool) -> Tuple[float, Optional[float]]:
        """Calculate MAIN and HEDGE sums based on unit"""
        if has_hedge:
            main_sum = 2 * self.config.unit
            hedge_sum = 1 * self.config.unit
        else:
            main_sum = 1 * self.config.unit
            hedge_sum = None
        
        return (main_sum, hedge_sum)
    
    def calculate_pnl(
        self,
        main_odds: float,
        main_sum: float,
        hedge_odds: Optional[float],
        hedge_sum: Optional[float]
    ) -> Dict[str, Any]:
        """Calculate P&L for all scenarios"""
        pnl = {}
        
        # Scenario A: MAIN win, HEDGE lose
        if hedge_sum:
            pnl['A_MAIN_win_HEDGE_lose'] = main_sum * (main_odds - 1) - hedge_sum
        else:
            pnl['A_MAIN_win'] = main_sum * (main_odds - 1)
        
        # Scenario B: MAIN lose, HEDGE win
        if hedge_sum and hedge_odds:
            pnl['B_MAIN_lose_HEDGE_win'] = hedge_sum * (hedge_odds - 1) - main_sum
        elif hedge_sum:
            pnl['B_MAIN_lose_HEDGE_win'] = -main_sum  # Hedge odds unknown
        
        # Scenario C: BOTH win (if applicable)
        if hedge_sum and hedge_odds:
            # Check if both can win (usually correlated, so often not applicable)
            # For set winner + handicap/total, they can both win
            pnl['C_BOTH_win'] = main_sum * (main_odds - 1) + hedge_sum * (hedge_odds - 1)
            pnl['C_applicable'] = True
        else:
            pnl['C_BOTH_win'] = None
            pnl['C_applicable'] = False
        
        # Scenario D: BOTH lose
        if hedge_sum:
            pnl['D_BOTH_lose'] = -(main_sum + hedge_sum)
        else:
            pnl['D_BOTH_lose'] = -main_sum
        
        return pnl
    
    def check_signal(self, event: Dict[str, Any]) -> Optional[Signal]:
        """
        Check if event triggers REVERSAL_NOT_END signal.
        Returns Signal or None
        """
        match_id = event.get('match_id')
        if not match_id:
            return None
        
        # Update history
        if match_id not in self.match_history:
            self.match_history[match_id] = []
        self.match_history[match_id].append(event)
        
        # Keep only last 10 events per match
        if len(self.match_history[match_id]) > 10:
            self.match_history[match_id] = self.match_history[match_id][-10:]
        
        # Rule 1: Must be live
        if event.get('status') != 'live':
            return None
        
        # Rule 2: Must NOT be end of set
        if not self.is_not_end_of_set(event):
            return None
        
        # Rule 3: Check current diff
        diff_data = self.get_current_diff(event)
        if not diff_data:
            return None
        
        diff, leading_player = diff_data
        
        # Rule 4: Diff must be in range [min_diff, max_diff]
        if diff < self.config.min_diff or diff > self.config.max_diff:
            return None
        
        # Rule 5: Check momentum (diff improved)
        trailing_player = 'p2' if leading_player == 'p1' else 'p1'
        if not self.check_momentum(match_id, diff, leading_player):
            return None
        
        # Rule 6: Find MAIN market for trailing player (reversal bet)
        main_data = self.find_main_market(event, trailing_player)
        if not main_data:
            return None
        
        main_market, main_odds = main_data
        
        # Rule 7: Find HEDGE market (optional)
        hedge_data = self.find_hedge_market(event, trailing_player)
        has_hedge = hedge_data is not None
        
        if hedge_data:
            hedge_market, hedge_odds = hedge_data
        else:
            hedge_market, hedge_odds = None, None
        
        # Calculate sums
        main_sum, hedge_sum = self.calculate_sums(has_hedge)
        
        # Calculate P&L
        pnl_data = self.calculate_pnl(main_odds, main_sum, hedge_odds, hedge_sum)
        
        # Build match name
        players = event.get('players', {})
        match_name = f"{players.get('p1', 'P1')} vs {players.get('p2', 'P2')}"
        
        # Build reason
        reason = f"REVERSAL_NOT_END: {trailing_player} отстаёт на {diff}, моментум +{self.config.momentum_improvement}"
        
        return Signal(
            match_id=match_id,
            match_name=match_name,
            reason=reason,
            main_market=main_market,
            main_odds=main_odds,
            main_sum=main_sum,
            hedge_market=hedge_market,
            hedge_odds=hedge_odds,
            hedge_sum=hedge_sum,
            pnl_data=pnl_data,
            raw_event=event
        )



