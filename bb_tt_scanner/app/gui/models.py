"""Table model for matches display"""
from typing import Dict, Any, Optional
from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from datetime import datetime


class MatchesTableModel(QAbstractTableModel):
    """Table model for displaying matches"""
    
    COLUMNS = [
        "Match", "League", "Sets", "Points", 
        "Odds Main", "Odds Hedge", "Status", "Reason", "Updated"
    ]
    
    def __init__(self):
        super().__init__()
        self.events: Dict[str, Dict[str, Any]] = {}
        self.signals: Dict[str, Any] = {}
    
    def update_events(self, events: Dict[str, Dict[str, Any]]):
        """Update events data"""
        self.beginResetModel()
        self.events = events
        self.endResetModel()
    
    def update_signal(self, match_id: str, signal_data: Optional[Dict[str, Any]]):
        """Update signal data for match"""
        if signal_data:
            self.signals[match_id] = signal_data
        elif match_id in self.signals:
            del self.signals[match_id]
        
        # Trigger update for this row
        row = self._get_row_for_match(match_id)
        if row >= 0:
            self.dataChanged.emit(
                self.index(row, 0),
                self.index(row, self.columnCount() - 1)
            )
    
    def _get_row_for_match(self, match_id: str) -> int:
        """Get row index for match_id"""
        matches = list(self.events.keys())
        try:
            return matches.index(match_id)
        except ValueError:
            return -1
    
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.events)
    
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return None
    
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        
        row = index.row()
        col = index.column()
        
        matches = list(self.events.keys())
        if row >= len(matches):
            return None
        
        match_id = matches[row]
        event = self.events[match_id]
        signal = self.signals.get(match_id)
        
        if role == Qt.DisplayRole:
            return self._get_display_data(event, signal, col)
        elif role == Qt.BackgroundRole:
            return self._get_background_color(event, signal)
        elif role == Qt.ForegroundRole:
            return self._get_foreground_color(event, signal)
        
        return None
    
    def _get_display_data(self, event: Dict[str, Any], signal: Optional[Dict[str, Any]], col: int) -> str:
        """Get display data for cell"""
        players = event.get('players', {})
        match_name = f"{players.get('p1', 'P1')} vs {players.get('p2', 'P2')}"
        
        if col == 0:  # Match
            return match_name
        elif col == 1:  # League
            return event.get('league', '') or ''
        elif col == 2:  # Sets
            score_sets = event.get('score_sets')
            return score_sets or '-'
        elif col == 3:  # Points
            score_points = event.get('score_points_current_set')
            return score_points or '-'
        elif col == 4:  # Odds Main
            if signal:
                return f"{signal.get('main_market', '')} @ {signal.get('main_odds', 0):.2f}"
            return '-'
        elif col == 5:  # Odds Hedge
            if signal and signal.get('hedge_market'):
                return f"{signal.get('hedge_market', '')} @ {signal.get('hedge_odds', 0):.2f}"
            return '-'
        elif col == 6:  # Status
            status = event.get('_status', 'WATCH')
            return status
        elif col == 7:  # Reason
            if signal:
                return signal.get('reason', '')
            return '-'
        elif col == 8:  # Updated
            last_seen = event.get('_last_seen')
            if last_seen:
                if isinstance(last_seen, datetime):
                    return last_seen.strftime("%H:%M:%S")
                return str(last_seen)
            return '-'
        
        return ''
    
    def _get_background_color(self, event: Dict[str, Any], signal: Optional[Dict[str, Any]]):
        """Get background color based on status"""
        from PySide6.QtGui import QColor
        
        status = event.get('_status', 'WATCH')
        
        if status == 'SIGNAL':
            return QColor(255, 200, 200)  # Light red
        elif status == 'CANDIDATE':
            return QColor(255, 255, 200)  # Light yellow
        elif status == 'STALE':
            return QColor(240, 240, 240)  # Light gray
        
        return None
    
    def _get_foreground_color(self, event: Dict[str, Any], signal: Optional[Dict[str, Any]]):
        """Get foreground color"""
        from PySide6.QtGui import QColor
        
        status = event.get('_status', 'WATCH')
        
        if status == 'SIGNAL':
            return QColor(200, 0, 0)  # Dark red
        
        return None



