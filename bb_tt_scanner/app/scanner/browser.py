"""Playwright browser manager with persistent context"""
import asyncio
from pathlib import Path
from typing import Optional, Callable, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from loguru import logger


class BrowserManager:
    """Manages Playwright browser with persistent context"""
    
    def __init__(self, profile_path: str = "./bb_profile"):
        self.profile_path = Path(profile_path)
        self.profile_path.mkdir(exist_ok=True)
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_connected = False
        self.network_callback: Optional[Callable[[dict], None]] = None
    
    async def start(self):
        """Start browser with persistent context"""
        try:
            self.playwright = await async_playwright().start()
            
            # Launch browser with persistent context
            self.browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_path),
                headless=False,
                viewport={'width': 1280, 'height': 720},
                args=['--disable-blink-features=AutomationControlled']
            )
            
            # Get or create page
            pages = self.browser.pages
            if pages:
                self.page = pages[0]
            else:
                self.page = await self.browser.new_page()
            
            # Setup network interception
            await self._setup_network_interception()
            
            self.is_connected = True
            logger.info("Browser started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            raise
    
    async def _setup_network_interception(self):
        """Setup network request/response interception"""
        if not self.page:
            return
        
        async def handle_response(response):
            try:
                url = response.url
                # Check if it's a relevant API endpoint
                if any(keyword in url.lower() for keyword in ['api', 'event', 'match', 'live', 'sport', 'betboom']):
                    try:
                        # Check content type
                        content_type = response.headers.get('content-type', '')
                        if 'json' not in content_type.lower():
                            return
                        
                        content = await response.text()
                        if content and len(content) > 10:  # Minimum content length
                            # Try to parse as JSON
                            try:
                                import json
                                data = json.loads(content)
                                if self.network_callback:
                                    self.network_callback({
                                        'type': 'response',
                                        'url': url,
                                        'data': data
                                    })
                            except json.JSONDecodeError:
                                pass
                            except Exception as e:
                                logger.debug(f"JSON parse error: {e}")
                    except Exception as e:
                        logger.debug(f"Response read error: {e}")
            except Exception as e:
                logger.debug(f"Network interception error: {e}")
        
        self.page.on('response', handle_response)
    
    async def navigate_to_live(self, url: str = "https://betboom.ru/sport/table-tennis?period=all&type=live"):
        """Navigate to live table tennis page"""
        if not self.page:
            raise RuntimeError("Browser not started")
        
        try:
            await self.page.goto(url, wait_until='networkidle', timeout=60000)
            logger.info(f"Navigated to: {url}")
            
            # Wait for page to load
            await asyncio.sleep(3)
            
        except Exception as e:
            logger.error(f"Navigation error: {e}")
            raise
    
    async def check_login_required(self) -> bool:
        """Check if login is required"""
        if not self.page:
            return True
        
        try:
            # Check for login indicators
            login_selectors = [
                'button:has-text("Войти")',
                'a:has-text("Войти")',
                '[data-testid="login"]',
                '.login-button'
            ]
            
            for selector in login_selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element:
                        return True
                except:
                    continue
            
            # Check URL for login redirect
            current_url = self.page.url
            if 'login' in current_url.lower() or 'auth' in current_url.lower():
                return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Login check error: {e}")
            return False
    
    def set_network_callback(self, callback: Callable[[dict], None]):
        """Set callback for network data"""
        self.network_callback = callback
    
    async def open_live_page(self):
        """Open live page in browser (for manual viewing)"""
        if not self.page:
            return
        
        url = "https://betboom.ru/sport/table-tennis?period=all&type=live"
        await self.page.goto(url)
    
    async def stop(self):
        """Stop browser"""
        try:
            if self.context:
                await self.context.close()
            elif self.browser:
                await self.browser.close()
            
            if self.playwright:
                await self.playwright.stop()
            
            self.is_connected = False
            logger.info("Browser stopped")
            
        except Exception as e:
            logger.error(f"Error stopping browser: {e}")
    
    async def reconnect(self):
        """Reconnect browser after crash"""
        logger.warning("Attempting browser reconnect...")
        await self.stop()
        await asyncio.sleep(2)
        await self.start()

