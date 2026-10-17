"""Create an H.264 sharing copy without changing the original recording."""
import os
import subprocess
import sys
from pathlib import Path

import cv2


def _ffmpeg_path():
    candidates = [
        Path(sys.executable).parent / "ffmpeg.exe",
        Path(getattr(sys, "_MEIPASS", "")) / "ffmpeg.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    for folder in (Path(sys.executable).parent, Path(getattr(sys, "_MEIPASS", ""))):
        for candidate in folder.glob("ffmpeg*.exe"):
            return str(candidate)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("Không tìm thấy FFmpeg để xuất video H.264.") from exc


def export_for_zalo(source: str, output_dir: str) -> str:
    """Transcode a finished recording to a shareable MP4, targeting under 90 MB."""
    if not os.path.isfile(source) or os.path.getsize(source) == 0:
        raise ValueError("Video gốc không tồn tại hoặc trống.")
    os.makedirs(output_dir, exist_ok=True)
    target = os.path.join(output_dir, Path(source).stem + "_Zalo.mp4")
    temporary = os.path.join(output_dir, Path(source).stem + "_Zalo.tmp.mp4")
    if os.path.exists(target):
        return target

    capture = cv2.VideoCapture(source)
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = frames / fps if fps > 0 and frames > 0 else 0
    finally:
        capture.release()
    if duration <= 0:
        raise ValueError("Không đọc được thời lượng video gốc.")

    # Leave headroom for MP4 overhead; input recordings have no audio.
    bitrate = max(250, min(1800, int(88 * 1024 * 1024 * 8 / duration / 1000)))
    args = [
        _ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", source, "-map", "0:v:0", "-an", "-vf", "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-b:v", f"{bitrate}k", "-maxrate", f"{bitrate}k", "-bufsize", f"{bitrate * 2}k",
        "-movflags", "+faststart", temporary,
    ]
    try:
        result = subprocess.run(args, capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0 or not os.path.isfile(temporary) or os.path.getsize(temporary) == 0:
            raise RuntimeError((result.stderr or "FFmpeg không tạo được video.")[-1000:])
        if os.path.getsize(temporary) > 95 * 1024 * 1024:
            raise RuntimeError("Video xuất vượt 95 MB. Hãy chia video thành đoạn ngắn hơn.")
        os.replace(temporary, target)
        return target
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
