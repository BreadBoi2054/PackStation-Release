"""Create shareable H.264 MP4 copies sized for Shopee, TikTok Shop, or Zalo without altering original recordings."""
import os
import subprocess
import sys
from pathlib import Path

import cv2

EXPORT_PRESETS = {
    "shopee_30": {
        "label": "Shopee (<30MB)",
        "target_mb": 27.5,
        "max_mb": 30.0,
        "suffix": "Shopee30M",
        "scale": "1280:720",
    },
    "shopee_10": {
        "label": "Shopee CSKH (<10MB)",
        "target_mb": 8.8,
        "max_mb": 10.0,
        "suffix": "Shopee10M",
        "scale": "960:540",
    },
    "tiktok_50": {
        "label": "TikTok Shop (<50MB)",
        "target_mb": 46.0,
        "max_mb": 50.0,
        "suffix": "TikTok50M",
        "scale": "1280:720",
    },
    "zalo_90": {
        "label": "Zalo (<90MB)",
        "target_mb": 88.0,
        "max_mb": 95.0,
        "suffix": "Zalo",
        "scale": "1280:720",
    },
}

EXPORT_LABEL_TO_PRESET = {cfg["label"]: key for key, cfg in EXPORT_PRESETS.items()}


def _ffmpeg_path() -> str:
    exe_dir = Path(sys.executable).parent
    meipass_dir = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", "") else None
    search_dirs = [exe_dir, exe_dir / "_internal"]
    if meipass_dir:
        search_dirs.append(meipass_dir)

    for folder in search_dirs:
        direct = folder / "ffmpeg.exe"
        if direct.is_file():
            return str(direct)
        if folder.is_dir():
            for candidate in folder.glob("ffmpeg*.exe"):
                if candidate.is_file():
                    return str(candidate)

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("Không tìm thấy FFmpeg để xuất video H.264.") from exc


def _inspect_video(source: str) -> tuple[float, str]:
    capture = cv2.VideoCapture(source)
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        fourcc = int(capture.get(cv2.CAP_PROP_FOURCC) or 0)
        fourcc_str = "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4)).lower()
        duration = frames / fps if fps > 0 and frames > 0 else 0.0
        return duration, fourcc_str
    finally:
        capture.release()


def export_for_platform(source: str, output_dir: str, preset_key: str = "shopee_30") -> str:
    """Transcode or fast-remux a finished recording into an MP4 meeting Shopee/TikTok/Zalo caps."""
    if not os.path.isfile(source) or os.path.getsize(source) == 0:
        raise ValueError("Video gốc không tồn tại hoặc trống.")

    preset = EXPORT_PRESETS.get(preset_key, EXPORT_PRESETS["shopee_30"])
    os.makedirs(output_dir, exist_ok=True)
    stem = Path(source).stem
    target = os.path.join(output_dir, f"{stem}_{preset['suffix']}.mp4")
    temporary = os.path.join(output_dir, f"{stem}_{preset['suffix']}.tmp.mp4")

    if os.path.exists(target) and os.path.getsize(target) > 0:
        if os.path.getmtime(target) >= os.path.getmtime(source):
            return target

    ffmpeg_exe = _ffmpeg_path()
    source_size = os.path.getsize(source)
    duration, fourcc_str = _inspect_video(source)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        # Fast stream copy when source is already H.264 and fits under target MB
        if fourcc_str in ("avc1", "h264", "x264") and source_size <= int(preset["target_mb"] * 1024 * 1024):
            copy_args = [
                ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", source, "-map", "0:v:0", "-an", "-c:v", "copy",
                "-movflags", "+faststart", temporary,
            ]
            copy_res = subprocess.run(
                copy_args, capture_output=True, text=True, timeout=120, creationflags=creation_flags
            )
            if (
                copy_res.returncode == 0
                and os.path.isfile(temporary)
                and 0 < os.path.getsize(temporary) <= int(preset["max_mb"] * 1024 * 1024)
            ):
                os.replace(temporary, target)
                return target
            if os.path.exists(temporary):
                os.remove(temporary)

        if duration <= 0:
            raise ValueError("Không đọc được thời lượng video gốc.")

        target_bits = preset["target_mb"] * 1024 * 1024 * 8
        bitrate = max(180, min(1800, int(target_bits / duration / 1000)))
        scale_filter = f"scale={preset['scale']}:force_original_aspect_ratio=decrease:force_divisible_by=2"
        args = [
            ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", source, "-map", "0:v:0", "-an", "-vf", scale_filter,
            "-threads", "2", "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-b:v", f"{bitrate}k", "-maxrate", f"{bitrate}k", "-bufsize", f"{bitrate * 2}k",
            "-movflags", "+faststart", temporary,
        ]
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=300, creationflags=creation_flags
        )
        if result.returncode != 0 or not os.path.isfile(temporary) or os.path.getsize(temporary) == 0:
            raise RuntimeError((result.stderr or "FFmpeg không tạo được video.")[-1000:])
        max_bytes = int(preset["max_mb"] * 1024 * 1024)
        if os.path.getsize(temporary) > max_bytes:
            raise RuntimeError(f"Video xuất vượt {int(preset['max_mb'])} MB. Hãy thử gói dung lượng cao hơn hoặc cắt ngắn.")
        os.replace(temporary, target)
        return target
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except Exception:
                pass


def export_for_zalo(source: str, output_dir: str) -> str:
    """Backward-compatible helper for Zalo export (<90 MB)."""
    return export_for_platform(source, output_dir, preset_key="zalo_90")
