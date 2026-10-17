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
        self._had_plaintext_credentials = False
        self._dpapi_migration_warning = False
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._deep_merge(self.data, saved)
                self._decrypt_stations_in_memory()
            except Exception as e:
                from core.logger import get_logger
                get_logger().error(f"[Config] Load error: {e}")

    def _deep_merge(self, base: dict, override: dict):
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def _decrypt_stations_in_memory(self):
        """Decrypt any encrypted RTSP credentials loaded from disk into runtime memory."""
        stations = self.data.get("stations", {})
        if not isinstance(stations, dict):
            return
        for st in stations.values():
            if not isinstance(st, dict):
                continue
            for key in ("camera_source", "camera_source_2", "camera_source_3"):
                val = st.get(key, "")
                if isinstance(val, str) and val:
                    if self._has_plaintext_rtsp_password(val):
                        self._had_plaintext_credentials = True
                    st[key] = self.decrypt_rtsp_url(val)
            if "cameras" in st and isinstance(st["cameras"], list):
                new_cams = []
                for c in st["cameras"]:
                    if isinstance(c, str) and c:
                        if self._has_plaintext_rtsp_password(c):
                            self._had_plaintext_credentials = True
                        new_cams.append(self.decrypt_rtsp_url(c))
                    else:
                        new_cams.append(c)
                st["cameras"] = new_cams

    @classmethod
    def _encrypt_stations_for_disk(cls, data_dict: dict) -> dict:
        """Return a deep copy of config data with all RTSP passwords encrypted via DPAPI for disk storage."""
        import copy
        out = copy.deepcopy(data_dict)
        stations = out.get("stations", {})
        if isinstance(stations, dict):
            for st in stations.values():
                if not isinstance(st, dict):
                    continue
                for key in ("camera_source", "camera_source_2", "camera_source_3"):
                    val = st.get(key, "")
                    if isinstance(val, str) and val:
                        st[key] = cls.encrypt_rtsp_url(val)
                if "cameras" in st and isinstance(st["cameras"], list):
                    st["cameras"] = [
                        cls.encrypt_rtsp_url(c) if isinstance(c, str) and c else c
                        for c in st["cameras"]
                    ]
        return out

    def migrate_plaintext_credentials(self) -> bool:
        """Convert any legacy plaintext RTSP passwords on disk to DPAPI-encrypted format."""
        if self._had_plaintext_credentials:
            self.save()
            self._had_plaintext_credentials = False
            return True
        return False

    def save(self):
        try:
            disk_data = self._encrypt_stations_for_disk(self.data)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(disk_data, f, indent=2, ensure_ascii=False)
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
        """Get list of decrypted camera URLs for station, supporting dynamic count."""
        st = self.get_station(station_id)
        if "cameras" in st and isinstance(st["cameras"], list) and st["cameras"]:
            return [self.decrypt_rtsp_url(str(c)) for c in st["cameras"]]
        # Fallback to legacy fields
        cams = []
        for k in ["camera_source", "camera_source_2", "camera_source_3"]:
            val = st.get(k, "").strip()
            if val:
                cams.append(self.decrypt_rtsp_url(val))
        return cams if cams else [""]

    def set_station_cameras(self, cameras: list, station_id: int = 1):
        """Set list of camera URLs for station (decrypted in memory, encrypted on disk)."""
        st = self.get_station(station_id)
        decrypted_cams = [self.decrypt_rtsp_url(c.strip()) for c in cameras]
        st["cameras"] = decrypted_cams
        st["camera_source"] = decrypted_cams[0] if len(decrypted_cams) > 0 else ""
        st["camera_source_2"] = decrypted_cams[1] if len(decrypted_cams) > 1 else ""
        st["camera_source_3"] = decrypted_cams[2] if len(decrypted_cams) > 2 else ""
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

    # ── Windows DPAPI Credential Protection for RTSP URLs ──
    _DPAPI_ENTROPY = b"PackStation-Camera-Cred-v1"

    @classmethod
    def encrypt_secret(cls, plain_text: str) -> str:
        """Encrypt a credential string using Windows DPAPI (LocalMachine scope for station portability across Windows users on the same PC)."""
        if not plain_text:
            return ""
        if plain_text.startswith("ENC[") and plain_text.endswith("]"):
            return plain_text
        raw_bytes = plain_text.encode("utf-8")
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                class DATA_BLOB(ctypes.Structure):
                    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

                crypt32 = ctypes.windll.crypt32
                kernel32 = ctypes.windll.kernel32

                in_buf = ctypes.create_string_buffer(raw_bytes, len(raw_bytes))
                in_blob = DATA_BLOB(len(raw_bytes), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))

                ent_buf = ctypes.create_string_buffer(cls._DPAPI_ENTROPY, len(cls._DPAPI_ENTROPY))
                ent_blob = DATA_BLOB(len(cls._DPAPI_ENTROPY), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))

                out_blob = DATA_BLOB()
                # CRYPTPROTECT_UI_FORBIDDEN (0x1) | CRYPTPROTECT_LOCAL_MACHINE (0x4)
                flags = 0x01 | 0x04
                if crypt32.CryptProtectData(
                    ctypes.byref(in_blob), None, ctypes.byref(ent_blob), None, None, flags, ctypes.byref(out_blob)
                ):
                    try:
                        enc_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
                        b64 = base64.urlsafe_b64encode(enc_bytes).decode("ascii")
                        return f"ENC[dpapi:{b64}]"
                    finally:
                        kernel32.LocalFree(out_blob.pbData)
            except Exception:
                pass
        # Fallback if DPAPI unavailable
        b64 = base64.urlsafe_b64encode(raw_bytes).decode("ascii")
        return f"ENC[b64:{b64}]"

    @classmethod
    def decrypt_secret(cls, token: str) -> str:
        """Decrypt an ENC[dpapi:...] or ENC[b64:...] credential token. Returns '' if machine key mismatches."""
        if not token:
            return ""
        if not (token.startswith("ENC[") and token.endswith("]")):
            return token
        inner = token[4:-1]
        if inner.startswith("dpapi:"):
            b64_part = inner[len("dpapi:"):]
            if os.name == "nt":
                try:
                    import ctypes
                    from ctypes import wintypes

                    class DATA_BLOB(ctypes.Structure):
                        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

                    crypt32 = ctypes.windll.crypt32
                    kernel32 = ctypes.windll.kernel32

                    enc_bytes = base64.urlsafe_b64decode(b64_part.encode("ascii"))
                    in_buf = ctypes.create_string_buffer(enc_bytes, len(enc_bytes))
                    in_blob = DATA_BLOB(len(enc_bytes), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))

                    ent_buf = ctypes.create_string_buffer(cls._DPAPI_ENTROPY, len(cls._DPAPI_ENTROPY))
                    ent_blob = DATA_BLOB(len(cls._DPAPI_ENTROPY), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))

                    out_blob = DATA_BLOB()
                    if crypt32.CryptUnprotectData(
                        ctypes.byref(in_blob), None, ctypes.byref(ent_blob), None, None, 0x01, ctypes.byref(out_blob)
                    ):
                        try:
                            dec_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
                            return dec_bytes.decode("utf-8")
                        finally:
                            kernel32.LocalFree(out_blob.pbData)
                except Exception:
                    pass
            from core.logger import get_logger
            get_logger().warning(
                "[Config] ⚠️ Không thể giải mã mật khẩu camera (cấu hình được tạo trên máy Windows khác). Vui lòng nhập lại mật khẩu camera trong Cài đặt."
            )
            return ""
        elif inner.startswith("b64:"):
            try:
                return base64.urlsafe_b64decode(inner[4:].encode("ascii")).decode("utf-8")
            except Exception:
                return ""
        return ""

    @staticmethod
    def _has_plaintext_rtsp_password(url: str) -> bool:
        if not url or not url.strip().lower().startswith("rtsp://"):
            return False
        body = url.strip()[7:]
        if "@" not in body:
            return False
        creds = body[:body.rfind("@")]
        if ":" not in creds:
            return False
        _, pwd = creds.split(":", 1)
        return bool(pwd and not (pwd.startswith("ENC[") and pwd.endswith("]")))

    @classmethod
    def encrypt_rtsp_url(cls, url: str) -> str:
        """Encrypt the password segment of an RTSP URL for safe storage in packstation-config.json."""
        if not url or not url.strip().lower().startswith("rtsp://"):
            return url
        u = url.strip()
        prefix = u[:7]
        body = u[7:]
        if "@" not in body:
            return u
        last_at = body.rfind("@")
        creds = body[:last_at]
        host_path = body[last_at + 1:]
        if ":" not in creds:
            return u
        user, pwd = creds.split(":", 1)
        if not pwd or (pwd.startswith("ENC[") and pwd.endswith("]")):
            return u
        enc_pwd = cls.encrypt_secret(pwd)
        return f"{prefix}{user}:{enc_pwd}@{host_path}"

    @classmethod
    def decrypt_rtsp_url(cls, url: str) -> str:
        """Decrypt the password segment of an RTSP URL for runtime use."""
        if not url or not url.strip().lower().startswith("rtsp://"):
            return url
        u = url.strip()
        prefix = u[:7]
        body = u[7:]
        if "@" not in body:
            return u
        last_at = body.rfind("@")
        creds = body[:last_at]
        host_path = body[last_at + 1:]
        if ":" not in creds:
            return u
        user, pwd = creds.split(":", 1)
        if not (pwd.startswith("ENC[") and pwd.endswith("]")):
            return u
        dec_pwd = cls.decrypt_secret(pwd)
        if dec_pwd:
            return f"{prefix}{user}:{dec_pwd}@{host_path}"
        return f"{prefix}{user}@{host_path}"

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
