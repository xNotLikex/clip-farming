"""
GitHub Update-Checker & Auto-Updater für Clip Farming Studio.
Prüft auf GitHub Releases und ermöglicht die nahtlose 1-Klick-Aktualisierung.
"""

import sys
import re
import os
import shutil
import urllib.request
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from src.version import APP_VERSION, GITHUB_REPO
from src.config import DATA_DIR, PROJECT_ROOT

def parse_version_tuple(v_str: str) -> tuple:
    """Extrahiert Versionszahlen wie '0.1.1' -> (0, 1, 1)."""
    clean = re.sub(r'^[^\d]*', '', str(v_str).strip())
    parts = []
    for p in clean.split('.'):
        try:
            parts.append(int(re.findall(r'\d+', p)[0]))
        except (IndexError, ValueError):
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])

def is_newer_version(remote_v: str, local_v: str = APP_VERSION) -> bool:
    """Prüft, ob remote_v echt größer ist als local_v."""
    try:
        return parse_version_tuple(remote_v) > parse_version_tuple(local_v)
    except Exception:
        return False

def check_for_updates() -> Dict[str, Any]:
    """
    Fragt die offizielle GitHub Releases API ab.
    Gibt Details zurück, wenn eine neue Version bereitsteht.
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": f"Clip-Farming-Studio/{APP_VERSION}"
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                tag = data.get("tag_name", "").strip()
                clean_tag = tag.lstrip("v")
                
                # Finde das Installer-Asset
                installer_url = ""
                installer_size_mb = 0.0
                for asset in data.get("assets", []):
                    name = asset.get("name", "").lower()
                    if "installer" in name and name.endswith(".exe"):
                        installer_url = asset.get("browser_download_url", "")
                        installer_size_mb = round(asset.get("size", 0) / (1024 * 1024), 1)
                        break
                    elif name.endswith(".exe") and not installer_url:
                        installer_url = asset.get("browser_download_url", "")
                        installer_size_mb = round(asset.get("size", 0) / (1024 * 1024), 1)

                is_newer = is_newer_version(clean_tag, APP_VERSION)
                return {
                    "success": True,
                    "update_available": is_newer,
                    "current_version": APP_VERSION,
                    "latest_version": clean_tag,
                    "release_name": data.get("name") or f"Version {tag}",
                    "release_notes": data.get("body") or "",
                    "download_url": installer_url or data.get("html_url"),
                    "installer_size_mb": installer_size_mb,
                    "published_at": data.get("published_at", "")
                }
    except Exception as e:
        return {
            "success": False,
            "update_available": False,
            "current_version": APP_VERSION,
            "error": str(e)
        }

    return {
        "success": True,
        "update_available": False,
        "current_version": APP_VERSION
    }

def download_and_run_installer(download_url: str) -> Dict[str, Any]:
    """
    Lädt das neue Installer-Release im Hintergrund herunter
    und startet den Windows Setup-Assistenten.
    """
    if not download_url or not download_url.startswith("http"):
        return {"success": False, "error": "Ungültige Download-URL"}

    target_dir = DATA_DIR / "updates"
    target_dir.mkdir(parents=True, exist_ok=True)
    installer_file = target_dir / "Clip-Farming-Setup-Update.exe"

    try:
        # Download mit Fortschritt
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": f"Clip-Farming-Studio/{APP_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=60) as response, open(installer_file, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)

        if not installer_file.exists() or installer_file.stat().st_size < 1024 * 1024:
            return {"success": False, "error": "Heruntergeladene Datei ist unvollständig"}

        # Starte den Installer mit aktuellem Installationspfad
        if sys.platform == "win32":
            current_install_dir = str(PROJECT_ROOT.resolve())
            try:
                import winreg
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\NotLike\Clip-Farming") as key:
                    winreg.SetValueEx(key, "InstallPath", 0, winreg.REG_SZ, current_install_dir)
            except Exception:
                pass
            
            # Starte Installer mit Zielverzeichnis-Vorgabe
            subprocess.Popen(f'"{installer_file}" /DIR="{current_install_dir}"')
        else:
            subprocess.Popen([str(installer_file)])
        
        return {
            "success": True,
            "message": "Installer gestartet. Clip Farming wird aktualisiert.",
            "file": str(installer_file)
        }
    except Exception as e:
        return {"success": False, "error": f"Download-Fehler: {e}"}
