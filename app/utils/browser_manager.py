import os
from pathlib import Path
from typing import Optional, Tuple

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright


class BrowserManager:
    """
    Manages a persistent Playwright browser instance for background automation.
    Handles browser launch, context management, and state persistence for logins.
    """

    _playwright: Optional[Playwright] = None
    _browser: Optional[Browser] = None
    _contexts: dict[str, BrowserContext] = {}

    @classmethod
    def _get_auth_path(cls, context_name: str) -> Path:
        """Returns the path to the state.json file for a given context."""
        return Path(__file__).parent / "auth" / context_name / "state.json"

    @classmethod
    def start_browser(cls) -> None:
        """Starts the Playwright instance and launches a persistent Chromium browser."""
        if cls._browser and cls._browser.is_connected():
            print("[BrowserManager] Browser already running.")
            return

        print("[BrowserManager] Starting background browser...")
        cls._playwright = sync_playwright().start()
        cls._browser = cls._playwright.chromium.launch(headless=False)
        print("[BrowserManager] Background browser started.")

    @classmethod
    def stop_browser(cls) -> None:
        """Closes all browser contexts and shuts down the browser."""
        if not cls._browser or not cls._browser.is_connected():
            return

        print("[BrowserManager] Stopping background browser...")
        for context_name, context in cls._contexts.items():
            try:
                state_path = cls._get_auth_path(context_name)
                state_path.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(state_path))
                print(f"[BrowserManager] Saved state for '{context_name}'.")
                context.close()
            except Exception as e:
                print(f"[BrowserManager] Error saving state for {context_name}: {e}")

        cls._browser.close()
        if cls._playwright:
            cls._playwright.stop()
        cls._browser = None
        cls._playwright = None
        cls._contexts = {}
        print("[BrowserManager] Background browser stopped.")

    @classmethod
    def get_page(cls, context_name: str) -> Page:
        """
        Gets a page from a named browser context.
        Creates the context and loads its saved authentication state if it exists.
        """
        cls.start_browser()
        if context_name in cls._contexts:
            return cls._contexts[context_name].new_page()

        print(f"[BrowserManager] Creating new context: '{context_name}'")
        auth_file = cls._get_auth_path(context_name)
        storage_state = str(auth_file) if auth_file.exists() else None

        context = cls._browser.new_context(storage_state=storage_state)
        cls._contexts[context_name] = context
        return context.new_page()

browser_manager = BrowserManager()