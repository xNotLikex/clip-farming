import time
import threading
from typing import Dict, Any, Optional
from playwright.sync_api import sync_playwright
from src.uploaders.account_manager import account_manager
from src.state import status_manager

_login_thread: Optional[threading.Thread] = None
_login_status = {"running": False, "platform": None, "message": ""}

def get_browser_login_status() -> Dict[str, Any]:
    global _login_status
    return _login_status

def start_tiktok_browser_login() -> Dict[str, Any]:
    global _login_thread, _login_status
    if _login_status.get("running"):
        return {"success": False, "message": "Ein Login-Fenster ist bereits aktiv!"}

    def worker():
        global _login_status
        _login_status = {"running": True, "platform": "tiktok", "message": "Chrome wird gestartet..."}
        status_manager.log("Starte interaktives TikTok-Loginfenster in Chrome...")
        status_manager.set_task("auth", "Warte auf TikTok-Login im Browser (QR-Code oder Passwort)...")

        try:
            with sync_playwright() as p:
                # Launch system Chrome so user can log in naturally (supports QR code scan)
                browser = p.chromium.launch(
                    channel="chrome",
                    headless=False,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--window-size=1080,850",
                    ]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    viewport={"width": 1080, "height": 850}
                )
                page = context.new_page()

                _login_status["message"] = "Bitte im geöffneten Fenster einloggen (z. B. QR-Code mit der TikTok-App scannen)..."
                status_manager.log("TikTok-Loginfenster geöffnet! Bitte im Fenster einloggen (z. B. QR-Code scannen)...")

                page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")

                start_time = time.time()
                timeout = 300  # 5 minutes
                found_session = None

                while time.time() - start_time < timeout:
                    # Check if browser was closed by user
                    try:
                        if not browser.is_connected() or len(context.pages) == 0:
                            status_manager.log("TikTok-Login vom Nutzer abgebrochen (Fenster geschlossen).")
                            _login_status = {"running": False, "platform": None, "message": "Login abgebrochen."}
                            status_manager.set_task("idle", "TikTok-Login abgebrochen.")
                            return
                    except Exception:
                        break

                    # Check cookies for sessionid
                    try:
                        cookies = context.cookies(["https://www.tiktok.com", "https://tiktok.com"])
                        for c in cookies:
                            c_name = c.get("name", "")
                            c_val = c.get("value", "")
                            if c_name in ["sessionid", "sessionid_ss"] and c_val and len(c_val) > 10:
                                found_session = c_val
                                break
                    except Exception:
                        pass

                    if found_session:
                        break

                    time.sleep(1.0)

                if found_session:
                    account_manager.save_tiktok_session(session_id=found_session, enabled=True)
                    status_manager.log("✅ TikTok-Konto erfolgreich über Browser verknüpft!")
                    status_manager.set_task("idle", "TikTok-Konto erfolgreich verbunden.")
                    _login_status = {"running": False, "platform": None, "message": "Erfolgreich verknüpft!"}
                    try:
                        page.wait_for_timeout(1500)
                        browser.close()
                    except Exception:
                        pass
                else:
                    status_manager.log("TikTok-Login Zeitlimit überschritten.")
                    status_manager.set_task("idle", "TikTok-Login abgelaufen.")
                    _login_status = {"running": False, "platform": None, "message": "Zeitlimit abgelaufen."}
                    try:
                        browser.close()
                    except Exception:
                        pass

        except Exception as e:
            status_manager.log(f"Fehler beim TikTok Browser-Login: {e}")
            status_manager.set_task("idle", "Fehler beim TikTok-Login.")
            _login_status = {"running": False, "platform": None, "message": f"Fehler: {e}"}

    _login_thread = threading.Thread(target=worker, daemon=True)
    _login_thread.start()
    return {"success": True, "message": "Browser-Fenster wird geöffnet..."}
