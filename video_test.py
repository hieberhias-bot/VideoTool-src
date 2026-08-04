import cv2
from processor import VisionProcessor

# Video öffnen
cap = cv2.VideoCapture("video_samples/fishing_data_test.mp4")
if not cap.isOpened():
    print("Video nicht gefunden oder nicht lesbar!")
    exit()

fishing_vision = VisionProcessor()
fps_counter = 0
import time
start = time.time()
frame_count = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break
    
    frame_count += 1
    # Fisch-Erkennung
    fish = fishing_vision.find_fish(frame)
    if fish:
        print(f"Frame {frame_count}: Fisch erkannt bei {fish}")
    
    fps_counter += 1
    elapsed = time.time() - start
    if elapsed > 1:
        print(f"FPS: {fps_counter / elapsed:.1f}")
        fps_counter = 0
        start = time.time()

print(f"Video fertig! {frame_count} Frames verarbeitet.")
