"""Configuration management - portable JSON config."""
import os
import sys
import json
import base64
import re

DEFAULTS = {
    "language": "vi-VN",
    "app_name": "PackStation",
    "video_dir": "",
    "max_stations": 4,
    "active_stations": 1,
    "auto_record": True,
    "video_retention_days": 30,
    "max_record_duration_minutes": 10,
    "duplicate_cooldown_seconds": 60,
    "sound_enabled": True,
    "sound_volume": 80,
    "auto_scan_enabled": True,
    "auto_scan_interval_ms": 1000,
    "startup_with_windows": False,
    "pin_code": "",
    "pin_protected_features": [],
    "stations": {
        "1": {
            "name": "Bàn 1",
            "camera_source": "",
            "camera_source_2": "",
            "camera_type": "rtsp",
            "scanner_port": "",
            "scanner_baudrate": 9600,
        }
    },
    "function_codes": {
        "end_order": "END",
        "cancel_order": "CANCEL",
        "manual_order": "MANUAL",
        "set_shift": "SHIFT",
    },
    "end_code_prefix": "KETTHUC",
    "cancel_code_prefix": "HUYDON",
    "manual_code_prefix": "DONTHUCONG",
    "shift_code_prefix": "SETCA",
    "current_shift": "",
}


class Config:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.config_path = os.path.join(base_dir, "packstation-config.json")
        self.data = dict(DEFAULTS)
        self._load()
        if not self.data.get("video_dir"):
            self.data["video_dir"] = os.path.join(base_dir, "Videos")
        os.makedirs(self.video_dir, exist_ok=True)

    def _load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._deep_merge(self.data, saved)
            except Exception as e:
                from core.logger import get_logger
                get_logger().error(f"[Config] Load error: {e}")

    def _deep_merge(self, base: dict, override: dict):
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            from core.logger import get_logger
            get_logger().error(f"[Config] Save error: {e}")

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value):
        self.data[key] = value
        self.save()

    def get_station(self, station_id: int) -> dict:
        stations = self.data.get("stations", {})
        key = str(station_id)
        if key not in stations:
            stations[key] = {
                "name": f"Bàn {station_id}",
                "camera_source": "",
                "camera_source_2": "",
                "camera_type": "rtsp",
                "scanner_port": "",
                "scanner_baudrate": 9600,
            }
            self.data["stations"] = stations
        return stations[key]

    def get_station_cameras(self, station_id: int = 1) -> list:
        """Get list of camera URLs for station, supporting dynamic count."""
        st = self.get_station(station_id)
        if "cameras" in st and isinstance(st["cameras"], list) and st["cameras"]:
            return [str(c) for c in st["cameras"]]
        # Fallback to legacy fields
        cams = []
        for k in ["camera_source", "camera_source_2", "camera_source_3"]:
            val = st.get(k, "").strip()
            if val:
                cams.append(val)
        return cams if cams else [""]

    def set_station_cameras(self, cameras: list, station_id: int = 1):
        """Set list of camera URLs for station and keep legacy fields in sync."""
        st = self.get_station(station_id)
        st["cameras"] = [c.strip() for c in cameras]
        st["camera_source"] = cameras[0].strip() if len(cameras) > 0 else ""
        st["camera_source_2"] = cameras[1].strip() if len(cameras) > 1 else ""
        st["camera_source_3"] = cameras[2].strip() if len(cameras) > 2 else ""
        self.data["stations"][str(station_id)] = st
        self.save()

    def is_pin_set(self) -> bool:
        """Check if manager PIN code is configured."""
        return bool(str(self.data.get("pin_code", "")).strip())

    def verify_pin(self, entered_pin: str) -> bool:
        """Verify entered PIN against stored PIN. If no PIN is configured, always returns True."""
        stored = str(self.data.get("pin_code", "")).strip()
        if not stored:
            return True
        import hashlib
        entered = str(entered_pin).strip()
        if entered == stored:
            return True
        hashed = hashlib.sha256(entered.encode("utf-8")).hexdigest()
        return hashed == stored

    def set_pin(self, new_pin: str):
        """Set or update manager PIN code (stored as SHA-256 hash)."""
        pin_str = str(new_pin).strip()
        if not pin_str:
            self.set("pin_code", "")
        else:
            import hashlib
            hashed = hashlib.sha256(pin_str.encode("utf-8")).hexdigest()
            self.set("pin_code", hashed)

    @staticmethod
    def mask_rtsp_url(url: str) -> str:
        """Mask credentials in RTSP URL for safe logging/display while preserving URL structure."""
        if not url:
            return ""
        return re.sub(r'(rtsp://[^:]+:)([^@]+)(@)', r'\1******\3', url, flags=re.IGNORECASE)

    @property
    def db_path(self) -> str:
        return os.path.join(self.base_dir, "packstation.db")

    @property
    def video_dir(self) -> str:
        return self.data.get("video_dir", os.path.join(self.base_dir, "Videos"))

    @property
    def language(self) -> str:
        return self.data.get("language", "vi-VN")

    @property
    def audio_dir(self) -> str:
        candidates = [
            os.path.join(self.base_dir, "audio"),
            os.path.join(self.base_dir, "_internal", "audio"),
            os.path.join(os.path.dirname(sys.executable), "audio"),
            os.path.join(os.path.dirname(sys.executable), "_internal", "audio"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "audio"),
        ]
        for c in candidates:
            if c and os.path.isdir(c):
                return c
        return os.path.join(self.base_dir, "audio")

    @property
    def i18n_dir(self) -> str:
        candidates = [
            os.path.join(self.base_dir, "i18n"),
            os.path.join(self.base_dir, "_internal", "i18n"),
            os.path.join(os.path.dirname(sys.executable), "i18n"),
            os.path.join(os.path.dirname(sys.executable), "_internal", "i18n"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "i18n"),
        ]
        for c in candidates:
            if c and os.path.isdir(c):
                return c
        return os.path.join(self.base_dir, "i18n")
