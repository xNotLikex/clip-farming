import sys
from pathlib import Path
from src.test_face_stability import analyze_video_faces

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

for p in Path("downloads/raw").glob("*.mp4"):
    analyze_video_faces(p)
