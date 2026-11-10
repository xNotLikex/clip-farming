import cv2
import numpy as np
from pathlib import Path

def analyze_video_faces(video_path: Path, max_frames=60):
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    cap = cv2.VideoCapture(str(video_path))
    
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Stichproben über das gesamte Video verteilen (nicht nur die ersten Sekunden)
    step = max(1, total_frames // max_frames)
    
    frame_faces = []
    crowd_frames = 0
    sampled_count = 0

    for f_idx in range(0, total_frames, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret:
            break
        sampled_count += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50))
        
        if len(faces) > 3:
            crowd_frames += 1
        elif len(faces) > 0:
            for (x, y, w, h) in faces:
                frame_faces.append((x, y, w, h))

    cap.release()

    print(f"\n--- Analyse: {video_path.name} ---")
    print(f"Sampled Frames: {sampled_count}, Crowd Frames (>3 Gesichter): {crowd_frames}")
    print(f"Detections gesamt: {len(frame_faces)}")

    if crowd_frames > 3:
        print("=> URTEIL: Crowd / IRL Szene erkannt! Keine Facecam.")
        return None

    if len(frame_faces) < (sampled_count * 0.3):
        print("=> URTEIL: Zu wenige Gesichter erkannt für permanente Facecam.")
        return None

    # Clustering: Finde den stabilsten Punkt
    # Berechne Mittelwert und Standardabweichung
    xs = [f[0] for f in frame_faces]
    ys = [f[1] for f in frame_faces]
    std_x = np.std(xs)
    std_y = np.std(ys)
    
    print(f"Position Varianz: std_x={std_x:.1f}px, std_y={std_y:.1f}px")

    # Eine echte Webcam steht still auf dem Schreibtisch -> Standardabweichung < 45px
    if std_x > 50 or std_y > 50:
        print("=> URTEIL: Position wackelt zu stark (std > 50px). Das ist eine Handkamera/IRL, keine Facecam!")
        return None

    avg_x = int(np.mean(xs))
    avg_y = int(np.mean(ys))
    avg_w = int(np.mean([f[2] for f in frame_faces]))
    avg_h = int(np.mean([f[3] for f in frame_faces]))

    print(f"=> URTEIL: ECHTE STATIONÄRE FACECAM ERKANNT bei ({avg_x}, {avg_y}, {avg_w}, {avg_h})!")
    return (avg_x, avg_y, avg_w, avg_h)

# Test mit beiden Clips
p1 = Path("downloads/raw/CooperativeFancyCaribouMcaT-Ne31g7MfGcNgDw2Y.mp4")
p2 = Path("downloads/raw/LongObliquePicklesDoritosChip-L-b-zr8NEaAUkcw0.mp4")

if p1.exists():
    analyze_video_faces(p1)
if p2.exists():
    analyze_video_faces(p2)
