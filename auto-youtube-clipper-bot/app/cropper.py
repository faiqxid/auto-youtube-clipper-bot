import logging
from pathlib import Path
from typing import Dict

import cv2
import numpy as np


def summarize_visual_activity(video_path: Path, logger: logging.Logger) -> Dict:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {"activity_level": "unknown", "avg_motion": 0.0}
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    duration = frame_count / fps if fps > 0 else 0

    prev_gray = None
    motions = []
    sample_step = max(1, int(fps // 2))
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % sample_step != 0:
            i += 1
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev_gray is not None:
            diff = cv2.absdiff(gray, prev_gray)
            motions.append(float(np.mean(diff)))
        prev_gray = gray
        i += 1
    cap.release()

    avg_motion = float(np.mean(motions)) if motions else 0.0
    if avg_motion > 22:
        level = "high"
    elif avg_motion > 12:
        level = "medium"
    else:
        level = "low"
    logger.info("Visual activity summary motion=%.2f level=%s", avg_motion, level)
    return {
        "duration_seconds": duration,
        "avg_motion": round(avg_motion, 2),
        "activity_level": level,
    }


def estimate_focus_x(
    video_path: Path,
    clip_start: float,
    clip_end: float,
    logger: logging.Logger,
) -> float:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0.5

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    if width <= 0:
        cap.release()
        return 0.5

    start_frame = int(clip_start * fps)
    end_frame = int(clip_end * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    face_detector = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    sample_step = max(1, int(fps // 4))
    idx = start_frame
    face_centers = []
    motion_centers = []
    prev_gray = None

    while idx <= end_frame:
        ok, frame = cap.read()
        if not ok:
            break
        if (idx - start_frame) % sample_step != 0:
            idx += 1
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        if len(faces) > 0:
            largest = max(faces, key=lambda b: b[2] * b[3])
            fx, _, fw, _ = largest
            face_centers.append(fx + (fw / 2))
        elif prev_gray is not None:
            diff = cv2.absdiff(gray, prev_gray)
            _, mask = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
            moments = cv2.moments(mask)
            if moments["m00"] > 0:
                cx = moments["m10"] / moments["m00"]
                motion_centers.append(cx)
        prev_gray = gray
        idx += 1

    cap.release()

    if face_centers:
        center = float(np.mean(face_centers))
        logger.info("Crop focus from face tracking: %.2f", center)
    elif motion_centers:
        center = float(np.mean(motion_centers))
        logger.info("Crop focus from motion tracking: %.2f", center)
    else:
        center = width / 2
        logger.info("Crop focus fallback to center: %.2f", center)

    ratio = center / width
    return max(0.0, min(1.0, ratio))
