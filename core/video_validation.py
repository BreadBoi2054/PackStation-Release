"""Cheap post-recording checks for evidence videos."""
import os

import cv2


def check_video(filepath: str, expected_seconds: float, health: dict) -> tuple[str, str, float]:
    """Read metadata and one frame after closing; never decode the whole video."""
    if not filepath or not os.path.isfile(filepath) or os.path.getsize(filepath) < 1024:
        return "missing", "Không tạo được file video", 0.0
    capture = cv2.VideoCapture(filepath)
    try:
        if not capture.isOpened():
            return "corrupt", "Không mở được video", 0.0
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        readable, _ = capture.read()
        if not readable or fps <= 0 or frames < 1:
            return "corrupt", "Không đọc được khung hình hoặc thời lượng", 0.0
        actual_seconds = frames / fps
    finally:
        capture.release()

    issues = []
    if health.get("error"):
        issues.append(str(health["error"]))
    if health.get("dropped", 0):
        issues.append(f"Mất {health['dropped']} khung hình")
    if expected_seconds >= 3 and actual_seconds < expected_seconds * 0.8:
        issues.append(f"Video ngắn hơn thời gian đơn ({actual_seconds:.1f}/{expected_seconds:.1f}s)")
    if issues:
        return "degraded", "; ".join(issues), actual_seconds
    return "ok", f"Đã kiểm tra {actual_seconds:.1f}s", actual_seconds
