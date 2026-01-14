"""Configuration constants"""

# BetBoom URL
LIVE_URL = "https://betboom.ru/sport/table-tennis?period=all&type=live"

# Signal thresholds
MAX_MATCH_ODDS = 1.20  # Фаворит по матчу <= 1.20
MIN_SET3_ODDS = 1.90   # Кф на 3-й сет >= 1.90

# Scan intervals (seconds)
SCAN_INTERVAL_MIN = 2
SCAN_INTERVAL_MAX = 5
SCAN_INTERVAL_ERROR = 8  # При ошибках

# Browser settings
MAX_DETAIL_PAGES = 2
BROWSER_TIMEOUT = 30000  # ms

# Anti-spam
ALERT_COOLDOWN = 180  # seconds
ALERT_REPEAT_THRESHOLD = 0.15  # Если кф вырос на 0.15, разрешить повторный алерт

# Storage
APP_DATA_DIR = "app_data"
SIGNALS_CSV = "signals.csv"
SIGNALS_DB = "signals.sqlite"
STATE_JSON = "state.json"
ERRORS_LOG = "errors.log"



