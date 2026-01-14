"""Main entry point for BB TT Scanner"""
import sys
import asyncio
from pathlib import Path
from loguru import logger
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
import qasync

from app.scanner.scanner import Scanner
from app.gui.main_window import MainWindow
from app.storage.database import Database


def setup_logging():
    """Setup logging"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    logger.add(
        log_dir / "app.log",
        rotation="10 MB",
        retention="7 days",
        level="INFO"
    )
    logger.add(
        sys.stderr,
        level="INFO"
    )


async def run_scanner(scanner: Scanner, window: MainWindow):
    """Run scanner with auto-start"""
    try:
        # Auto-start scanner
        logger.info("Auto-starting scanner...")
        await scanner.start()
        
        # Update window button
        window.start_btn.setText("Stop")
        
    except Exception as e:
        logger.error(f"Failed to start scanner: {e}")
        window.health_label.setText(f"Status: Error - {str(e)[:50]}")


def main():
    """Main entry point"""
    setup_logging()
    logger.info("Starting BB TT Scanner...")
    
    # Create Qt application
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # Setup async event loop
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    # Create database
    db = Database()
    
    # Create scanner
    scanner = Scanner()
    
    # Create main window
    window = MainWindow()
    window.scanner = scanner
    window.db = db
    
    # Connect scanner callbacks to window signals
    def on_event_update(event):
        window.scanner_signals.event_updated.emit(event)
    
    def on_signal(signal):
        window.scanner_signals.signal_detected.emit(signal)
    
    def on_status_change(status):
        window.scanner_signals.status_changed.emit(status)
    
    scanner.on_event_update = on_event_update
    scanner.on_signal = on_signal
    scanner.on_status_change = on_status_change
    
    # Setup start/stop button
    async def toggle_scan():
        if scanner.is_running:
            await scanner.stop()
            window.start_btn.setText("Start")
            window.health_label.setText("Status: Disconnected")
        else:
            await run_scanner(scanner, window)
    
    def toggle_scan_sync():
        try:
            asyncio.create_task(toggle_scan())
        except RuntimeError:
            # If no event loop, create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(toggle_scan())
    
    # Disconnect default handler if exists
    try:
        window.start_btn.clicked.disconnect()
    except:
        pass
    window.start_btn.clicked.connect(toggle_scan_sync)
    
    # Show window
    window.show()
    
    # Auto-start scanner
    QTimer.singleShot(1000, lambda: asyncio.create_task(run_scanner(scanner, window)))
    
    # Run event loop
    with loop:
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            # Cleanup
            if scanner.is_running:
                asyncio.run_coroutine_threadsafe(scanner.stop(), loop)
            loop.close()


if __name__ == "__main__":
    main()

