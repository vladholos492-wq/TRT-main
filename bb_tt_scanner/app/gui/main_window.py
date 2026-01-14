"""Main application window"""
import sys
import os
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableView, QLabel, QTextEdit, QGroupBox, QSystemTrayIcon,
    QMenu, QApplication, QMessageBox, QFileDialog, QDialog, QFormLayout,
    QSpinBox, QDoubleSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QIcon, QFont
from loguru import logger

from app.gui.models import MatchesTableModel
from app.engine.strategy import Signal, StrategyConfig


class SettingsDialog(QDialog):
    """Settings dialog"""
    
    def __init__(self, config: StrategyConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(400, 500)
        
        layout = QFormLayout(self)
        
        # Strategy settings
        self.min_diff_spin = QSpinBox()
        self.min_diff_spin.setRange(1, 10)
        self.min_diff_spin.setValue(config.min_diff)
        layout.addRow("Min diff (points):", self.min_diff_spin)
        
        self.max_diff_spin = QSpinBox()
        self.max_diff_spin.setRange(1, 10)
        self.max_diff_spin.setValue(config.max_diff)
        layout.addRow("Max diff (points):", self.max_diff_spin)
        
        self.odds_min_spin = QDoubleSpinBox()
        self.odds_min_spin.setRange(1.0, 10.0)
        self.odds_min_spin.setSingleStep(0.1)
        self.odds_min_spin.setValue(config.odds_min)
        layout.addRow("Odds min:", self.odds_min_spin)
        
        self.odds_max_spin = QDoubleSpinBox()
        self.odds_max_spin.setRange(1.0, 10.0)
        self.odds_max_spin.setSingleStep(0.1)
        self.odds_max_spin.setValue(config.odds_max)
        layout.addRow("Odds max:", self.odds_max_spin)
        
        self.unit_spin = QDoubleSpinBox()
        self.unit_spin.setRange(10.0, 1000.0)
        self.unit_spin.setSingleStep(10.0)
        self.unit_spin.setValue(config.unit)
        layout.addRow("Unit (₽):", self.unit_spin)
        
        # Buttons
        buttons = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addRow(buttons)
    
    def get_config(self) -> StrategyConfig:
        """Get updated config"""
        self.config.min_diff = self.min_diff_spin.value()
        self.config.max_diff = self.max_diff_spin.value()
        self.config.odds_min = self.odds_min_spin.value()
        self.config.odds_max = self.odds_max_spin.value()
        self.config.unit = self.unit_spin.value()
        return self.config


class ScannerSignals(QObject):
    """Signals for scanner events"""
    event_updated = Signal(dict)
    signal_detected = Signal(object)  # Signal object
    status_changed = Signal(str)


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BB TT Scanner")
        self.setGeometry(100, 100, 1200, 700)
        
        # Scanner will be set later
        self.scanner = None
        self.scanner_signals = ScannerSignals()
        self.last_signal: Optional[Signal] = None
        self.db = None  # Will be set from main
        
        # Setup UI
        self._setup_ui()
        self._setup_tray()
        self._setup_timers()
        
        # Connect signals
        self.scanner_signals.event_updated.connect(self._on_event_updated)
        self.scanner_signals.signal_detected.connect(self._on_signal_detected)
        self.scanner_signals.status_changed.connect(self._on_status_changed)
    
    def _setup_ui(self):
        """Setup UI components"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        
        # Left panel: Table
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # Top bar
        top_bar = self._create_top_bar()
        left_layout.addWidget(top_bar)
        
        # Table
        self.table = QTableView()
        self.table_model = MatchesTableModel()
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        left_layout.addWidget(self.table)
        
        main_layout.addWidget(left_panel, stretch=2)
        
        # Right panel: Last Signal
        right_panel = self._create_signal_panel()
        main_layout.addWidget(right_panel, stretch=1)
    
    def _create_top_bar(self) -> QWidget:
        """Create top bar with controls"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        
        # Start/Stop button
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._toggle_scan)
        layout.addWidget(self.start_btn)
        
        # Open Live button
        open_live_btn = QPushButton("Open Live")
        open_live_btn.clicked.connect(self._open_live)
        layout.addWidget(open_live_btn)
        
        # Settings button
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._show_settings)
        layout.addWidget(settings_btn)
        
        # Health status
        self.health_label = QLabel("Status: Disconnected")
        layout.addWidget(self.health_label)
        
        # Active matches
        self.matches_label = QLabel("Active: 0")
        layout.addWidget(self.matches_label)
        
        # Events/min
        self.events_label = QLabel("Events/min: 0")
        layout.addWidget(self.events_label)
        
        # Last update
        self.update_label = QLabel("Last update: -")
        layout.addWidget(self.update_label)
        
        layout.addStretch()
        
        return widget
    
    def _create_signal_panel(self) -> QWidget:
        """Create right panel for last signal"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Signal info group
        signal_group = QGroupBox("LAST SIGNAL")
        signal_layout = QVBoxLayout(signal_group)
        
        self.signal_match_label = QLabel("Match: -")
        signal_layout.addWidget(self.signal_match_label)
        
        self.signal_time_label = QLabel("Time: -")
        signal_layout.addWidget(self.signal_time_label)
        
        self.signal_main_label = QLabel("MAIN: -")
        signal_layout.addWidget(self.signal_main_label)
        
        self.signal_hedge_label = QLabel("HEDGE: -")
        signal_layout.addWidget(self.signal_hedge_label)
        
        layout.addWidget(signal_group)
        
        # P&L group
        pnl_group = QGroupBox("P&L Scenarios")
        pnl_layout = QVBoxLayout(pnl_group)
        
        self.pnl_text = QTextEdit()
        self.pnl_text.setReadOnly(True)
        self.pnl_text.setMaximumHeight(150)
        pnl_layout.addWidget(self.pnl_text)
        
        layout.addWidget(pnl_group)
        
        # Not end of set info
        not_end_group = QGroupBox("Почему это НЕ конец сета")
        not_end_layout = QVBoxLayout(not_end_group)
        
        self.not_end_label = QLabel("max(points) <= 8")
        not_end_layout.addWidget(self.not_end_label)
        
        layout.addWidget(not_end_group)
        
        # Copy bet text button
        copy_btn = QPushButton("Copy bet text")
        copy_btn.clicked.connect(self._copy_bet_text)
        layout.addWidget(copy_btn)
        
        # Export CSV button
        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self._export_csv)
        layout.addWidget(export_btn)
        
        layout.addStretch()
        
        return widget
    
    def _setup_tray(self):
        """Setup system tray"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.style().standardIcon(self.style().SP_ComputerIcon))
        
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self.show)
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(QApplication.quit)
        
        self.tray.setContextMenu(tray_menu)
        self.tray.show()
        self.tray.activated.connect(self._tray_activated)
    
    def _setup_timers(self):
        """Setup update timers"""
        # Update table every second
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_table)
        self.update_timer.start(1000)
        
        # Update health every 2 seconds
        self.health_timer = QTimer()
        self.health_timer.timeout.connect(self._update_health)
        self.health_timer.start(2000)
    
    def _toggle_scan(self):
        """Toggle scanner start/stop"""
        # This will be implemented in main.py with async
        pass
    
    def _open_live(self):
        """Open live page in browser"""
        if self.scanner and self.scanner.browser:
            # Use the existing event loop
            loop = asyncio.get_event_loop()
            if loop and loop.is_running():
                asyncio.create_task(self.scanner.browser.open_live_page())
            else:
                # Fallback: run in new event loop
                asyncio.run(self.scanner.browser.open_live_page())
    
    def _show_settings(self):
        """Show settings dialog"""
        if not self.scanner:
            return
        
        config = self.scanner.strategy.config
        dialog = SettingsDialog(config, self)
        if dialog.exec():
            self.scanner.strategy.config = dialog.get_config()
            QMessageBox.information(self, "Settings", "Settings saved")
    
    def _on_event_updated(self, event: Dict[str, Any]):
        """Handle event update"""
        # Update will be handled by _update_table
        pass
    
    def _on_signal_detected(self, signal: Signal):
        """Handle signal detection"""
        self.last_signal = signal
        
        # Update signal panel
        self._update_signal_panel(signal)
        
        # Play sound
        QApplication.beep()
        
        # Tray notification
        if hasattr(self, 'tray'):
            self.tray.showMessage(
                "Signal Detected",
                f"{signal.match_name}: {signal.reason}",
                QSystemTrayIcon.Information,
                5000
            )
        
        # Popup (non-blocking)
        msg = QMessageBox(self)
        msg.setWindowTitle("Signal Detected")
        msg.setText(f"Match: {signal.match_name}\nReason: {signal.reason}")
        msg.setIcon(QMessageBox.Information)
        msg.show()  # Non-blocking
        
        # Save to database
        if self.db:
            self.db.save_signal(
                match_id=signal.match_id,
                match_name=signal.match_name,
                reason=signal.reason,
                main_market=signal.main_market,
                main_odds=signal.main_odds,
                main_sum=signal.main_sum,
                hedge_market=signal.hedge_market,
                hedge_odds=signal.hedge_odds,
                hedge_sum=signal.hedge_sum,
                pnl_data=signal.pnl_data,
                raw_data=signal.raw_event
            )
    
    def _on_status_changed(self, status: str):
        """Handle status change"""
        status_text = {
            'connected': 'Connected',
            'disconnected': 'Disconnected',
            'waiting_login': 'Waiting for login...',
            'error': 'Error'
        }.get(status, status)
        
        self.health_label.setText(f"Status: {status_text}")
    
    def _update_table(self):
        """Update table with current events"""
        if not self.scanner:
            return
        
        events = self.scanner.get_events()
        self.table_model.update_events(events)
        
        # Update signals
        for match_id, signal in self.scanner.signals.items():
            signal_data = {
                'main_market': signal.main_market,
                'main_odds': signal.main_odds,
                'hedge_market': signal.hedge_market,
                'hedge_odds': signal.hedge_odds,
                'reason': signal.reason
            }
            self.table_model.update_signal(match_id, signal_data)
    
    def _update_health(self):
        """Update health indicators"""
        if not self.scanner:
            return
        
        active_matches = self.scanner.get_active_matches_count()
        self.matches_label.setText(f"Active: {active_matches}")
        
        events_per_min = self.scanner.events_per_minute
        self.events_label.setText(f"Events/min: {events_per_min}")
        
        if self.scanner.last_update_time:
            time_str = self.scanner.last_update_time.strftime("%H:%M:%S")
            self.update_label.setText(f"Last update: {time_str}")
    
    def _update_signal_panel(self, signal: Signal):
        """Update signal panel with signal data"""
        self.signal_match_label.setText(f"Match: {signal.match_name}")
        self.signal_time_label.setText(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        
        self.signal_main_label.setText(
            f"MAIN: {signal.main_market} @ {signal.main_odds:.2f} | {signal.main_sum:.0f}₽"
        )
        
        if signal.hedge_market:
            self.signal_hedge_label.setText(
                f"HEDGE: {signal.hedge_market} @ {signal.hedge_odds:.2f} | {signal.hedge_sum:.0f}₽"
            )
        else:
            self.signal_hedge_label.setText("HEDGE: -")
        
        # Update P&L
        pnl_text = self._format_pnl(signal.pnl_data)
        self.pnl_text.setPlainText(pnl_text)
        
        # Update not end of set
        event = signal.raw_event
        score_points = event.get('score_points_current_set', '')
        if score_points:
            try:
                p1_str, p2_str = score_points.split(':')
                p1 = int(p1_str.strip())
                p2 = int(p2_str.strip())
                max_points = max(p1, p2)
                self.not_end_label.setText(f"max(points) = {max_points} <= 8 ✓")
            except:
                self.not_end_label.setText("max(points) <= 8")
        else:
            self.not_end_label.setText("max(points) <= 8")
    
    def _format_pnl(self, pnl_data: Dict[str, Any]) -> str:
        """Format P&L data as text"""
        lines = []
        
        if 'A_MAIN_win_HEDGE_lose' in pnl_data:
            lines.append(f"A) MAIN win, HEDGE lose: {pnl_data['A_MAIN_win_HEDGE_lose']:.2f}₽")
        elif 'A_MAIN_win' in pnl_data:
            lines.append(f"A) MAIN win: {pnl_data['A_MAIN_win']:.2f}₽")
        
        if 'B_MAIN_lose_HEDGE_win' in pnl_data:
            lines.append(f"B) MAIN lose, HEDGE win: {pnl_data['B_MAIN_lose_HEDGE_win']:.2f}₽")
        
        if pnl_data.get('C_applicable'):
            lines.append(f"C) BOTH win: {pnl_data['C_BOTH_win']:.2f}₽")
        else:
            lines.append("C) BOTH win: not applicable")
        
        if 'D_BOTH_lose' in pnl_data:
            lines.append(f"D) BOTH lose: {pnl_data['D_BOTH_lose']:.2f}₽")
        
        return "\n".join(lines)
    
    def _copy_bet_text(self):
        """Copy bet text to clipboard"""
        if not self.last_signal:
            QMessageBox.warning(self, "No Signal", "No signal to copy")
            return
        
        signal = self.last_signal
        
        text_lines = [
            f"Match: {signal.match_name}",
            f"MAIN: {signal.main_market} @ {signal.main_odds:.2f} | {signal.main_sum:.0f}₽"
        ]
        
        if signal.hedge_market:
            text_lines.append(
                f"HEDGE: {signal.hedge_market} @ {signal.hedge_odds:.2f} | {signal.hedge_sum:.0f}₽"
            )
        
        text = "\n".join(text_lines)
        
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        
        QMessageBox.information(self, "Copied", "Bet text copied to clipboard")
    
    def _export_csv(self):
        """Export signals to CSV"""
        if not self.db:
            QMessageBox.warning(self, "Error", "Database not available")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "signals.csv", "CSV Files (*.csv)"
        )
        
        if file_path:
            success = self.db.export_csv(file_path)
            if success:
                QMessageBox.information(self, "Success", f"Exported to {file_path}")
            else:
                QMessageBox.warning(self, "Error", "Export failed")
    
    def _tray_activated(self, reason):
        """Handle tray icon activation"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
    
    def closeEvent(self, event):
        """Handle window close"""
        if hasattr(self, 'tray') and self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

