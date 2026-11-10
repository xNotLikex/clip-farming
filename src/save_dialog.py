"""
Natives Windows 'Speichern unter'-Dialogmodul für Clip-Farming.
Öffnet ein zentriertes, im Vordergrund liegendes Windows-Dateiauswahlfenster,
damit der Benutzer den Zielordner und Dateinamen frei wählen kann.
"""

import sys
import os
from pathlib import Path

def open_save_dialog(suggested_filename: str, initial_dir: str = "", title: str = "Video speichern unter...") -> str:
    if not initial_dir or not Path(initial_dir).exists():
        initial_dir = str(Path.home() / "Downloads")

    # Methode 1: Tkinter Common SaveFileDialog (modern, schnell, nativ Win32)
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        # Fenster im Vordergrund erzwingen
        root.wm_attributes("-topmost", True)
        root.focus_force()

        selected = filedialog.asksaveasfilename(
            parent=root,
            title=title,
            initialdir=initial_dir,
            initialfile=suggested_filename,
            defaultextension=".mp4",
            filetypes=[("MP4 Video (*.mp4)", "*.mp4"), ("Alle Dateien (*.*)", "*.*")]
        )
        root.destroy()
        if selected and str(selected).strip():
            return str(Path(selected).resolve())
        return ""
    except Exception as e:
        sys.stderr.write(f"Tkinter dialog exception: {e}\n")

    # Methode 2: PowerShell SaveFileDialog als zuverlässiges Fallback
    try:
        import subprocess
        # Escaping für PowerShell Single-Quotes
        safe_title = title.replace("'", "''")
        safe_file = suggested_filename.replace("'", "''")
        safe_dir = initial_dir.replace("'", "''")

        ps_script = f"""
[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null
$dlg = New-Object System.Windows.Forms.SaveFileDialog
$dlg.Title = '{safe_title}'
$dlg.Filter = 'MP4 Video (*.mp4)|*.mp4|Alle Dateien (*.*)|*.*'
$dlg.FileName = '{safe_file}'
$dlg.InitialDirectory = '{safe_dir}'
$dlg.RestoreDirectory = $true
$topForm = New-Object System.Windows.Forms.Form
$topForm.TopMost = $true
$res = $dlg.ShowDialog($topForm)
if ($res -eq [System.Windows.Forms.DialogResult]::OK) {{
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::WriteLine($dlg.FileName)
}}
"""
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        out = res.stdout.strip()
        if out and Path(out).parent.exists():
            return str(Path(out).resolve())
    except Exception as e:
        sys.stderr.write(f"PowerShell dialog exception: {e}\n")

    return ""

if __name__ == "__main__":
    suggested = sys.argv[1] if len(sys.argv) > 1 else "video.mp4"
    init_dir = sys.argv[2] if len(sys.argv) > 2 else ""
    dialog_title = sys.argv[3] if len(sys.argv) > 3 else "Video speichern unter..."

    target_path = open_save_dialog(suggested, init_dir, dialog_title)
    if target_path:
        # Sicheres UTF-8 Output für das aufrufende Programm
        sys.stdout.buffer.write(target_path.encode("utf-8"))
        sys.stdout.buffer.flush()
        sys.exit(0)
    else:
        sys.exit(1)
