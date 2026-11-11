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

    # Methode 1: Echter nativer Win32 GetSaveFileNameW Dialog (immer im Vordergrund, keine Abhängigkeiten)
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class OPENFILENAMEW(ctypes.Structure):
                _fields_ = [
                    ("lStructSize", wintypes.DWORD),
                    ("hwndOwner", wintypes.HWND),
                    ("hInstance", wintypes.HINSTANCE),
                    ("lpstrFilter", wintypes.LPCWSTR),
                    ("lpstrCustomFilter", wintypes.LPWSTR),
                    ("nMaxCustFilter", wintypes.DWORD),
                    ("nFilterIndex", wintypes.DWORD),
                    ("lpstrFile", wintypes.LPWSTR),
                    ("nMaxFile", wintypes.DWORD),
                    ("lpstrFileTitle", wintypes.LPWSTR),
                    ("nMaxFileTitle", wintypes.DWORD),
                    ("lpstrInitialDir", wintypes.LPCWSTR),
                    ("lpstrTitle", wintypes.LPCWSTR),
                    ("Flags", wintypes.DWORD),
                    ("nFileOffset", wintypes.WORD),
                    ("nFileExtension", wintypes.WORD),
                    ("lpstrDefExt", wintypes.LPCWSTR),
                    ("lCustData", wintypes.LPARAM),
                    ("lpfnHook", wintypes.LPVOID),
                    ("lpTemplateName", wintypes.LPCWSTR),
                    ("pvReserved", wintypes.LPVOID),
                    ("dwReserved", wintypes.DWORD),
                    ("FlagsEx", wintypes.DWORD)
                ]

            user32 = ctypes.windll.user32
            comdlg32 = ctypes.windll.comdlg32

            # Vordergrundfenster (Tauri/Browser) als Parent holen
            hwnd = user32.GetForegroundWindow()

            buf = ctypes.create_unicode_buffer(1024)
            if suggested_filename:
                buf.value = suggested_filename

            filters = "MP4 Video (*.mp4)\0*.mp4\0Alle Dateien (*.*)\0*.*\0\0"

            OFN_OVERWRITEPROMPT = 0x00000002
            OFN_PATHMUSTEXIST   = 0x00000800
            OFN_EXPLORER        = 0x00080000
            OFN_ENABLESIZING    = 0x00800000

            ofn = OPENFILENAMEW()
            ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
            ofn.hwndOwner = hwnd
            ofn.lpstrFilter = filters
            ofn.nFilterIndex = 1
            ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
            ofn.nMaxFile = 1024
            ofn.lpstrInitialDir = initial_dir if os.path.exists(initial_dir) else None
            ofn.lpstrTitle = title
            ofn.Flags = OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST | OFN_EXPLORER | OFN_ENABLESIZING
            ofn.lpstrDefExt = "mp4"

            if comdlg32.GetSaveFileNameW(ctypes.byref(ofn)):
                selected = buf.value
                if selected and str(selected).strip():
                    return str(Path(selected).resolve())
                return ""
            else:
                # Benutzer hat 'Abbrechen' geklickt
                return ""
        except Exception as e:
            sys.stderr.write(f"Win32 native dialog exception: {e}\n")

    # Methode 2: Tkinter SaveFileDialog
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
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

    # Methode 3: PowerShell SaveFileDialog als Fallback
    try:
        import subprocess
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
        sys.stdout.buffer.write(target_path.encode("utf-8"))
        sys.stdout.buffer.flush()
        sys.exit(0)
    else:
        sys.exit(1)
