import sys
import argparse
from pathlib import Path

# Windows UTF-8 Output Fix
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.config import ensure_directories, load_config
from src.database import get_db_connection, init_db
from src.logging_config import setup_logging

BANNER = r"""
  ╔══════════════════════════════════════════════════════════════╗
  ║      🎬 CLIP-FARMING AUTOPILOT (Twitch -> 9:16 Shorts)       ║
  ║         AI Facecam-Split • Karaoke Subtitles • Auto-Upload   ║
  ╚══════════════════════════════════════════════════════════════╝
"""

def show_status():
    """Zeigt Statistiken aus der lokalen Datenbank an."""
    config = load_config()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) FROM clips GROUP BY status")
        counts = dict(cursor.fetchall())
        
        cursor.execute("SELECT streamer, COUNT(*) FROM clips GROUP BY streamer")
        streamer_counts = dict(cursor.fetchall())

    print("\n📊 AKTUELLE PIPELINE STATISTIK:")
    print("-" * 45)
    print(f"  • Verarbeitete Clips (Abgeschlossen): {counts.get('completed', 0)}")
    print(f"  • In Warteschlange (Harvested):       {counts.get('harvested', 0)}")
    print(f"  • Fehlgeschlagen:                    {counts.get('failed', 0)}")
    print("-" * 45)
    print("📈 Clips nach Streamer:")
    for st, count in streamer_counts.items():
        print(f"  - {st:<20} {count} Clips")
    print("-" * 45)

def main():
    ensure_directories()
    setup_logging()
    init_db()
    print(BANNER)

    parser = argparse.ArgumentParser(description="Clip-Farming Autopilot Pipeline")
    parser.add_argument("--daemon", action="store_true", help="Startet den 24/7 Autopilot-Modus")
    parser.add_argument("--interval", type=int, default=15, help="Prüf-Intervall in Minuten für den Autopilot (Standard: 15)")
    parser.add_argument("--status", action="store_true", help="Zeigt aktuelle Statistiken an")
    parser.add_argument("--harvest-only", action="store_true", help="Lädt nur Clips herunter, ohne zu rendern")
    parser.add_argument("--reset-failed", action="store_true", help="Setzt fehlgeschlagene Clips zurück auf 'harvested'")
    
    args = parser.parse_args()

    if args.reset_failed:
        with get_db_connection() as conn:
            conn.execute("UPDATE clips SET status = 'harvested' WHERE status = 'failed'")
            conn.commit()
        print("[+] Fehlgeschlagene Clips wurden zurückgesetzt auf 'harvested'!")
        return

    if args.status:
        show_status()
        return

    from src.scheduler import PipelineOrchestrator
    orchestrator = PipelineOrchestrator()

    if args.harvest_only:
        print("[*] Modus: Nur Harvesting...")
        streamers = orchestrator.config.get("streamers", [])
        for s in streamers:
            if s.get("enabled", True):
                orchestrator.harvester.harvest_channel(s)
        print("[+] Harvesting abgeschlossen.")
        return

    if args.daemon:
        orchestrator.run_forever(interval_minutes=args.interval)
    else:
        print("[*] Starte einzelnen Durchlauf...")
        orchestrator.run_cycle()
        print("\n[+] Durchlauf beendet! Für 24/7 Modus starte mit: run.bat --daemon")

if __name__ == "__main__":
    main()
