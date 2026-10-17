"""Dahua / Imou NetSDK Manager - direct communication via Dahua protocol (port 37777).

Enables connecting to Imou and Dahua cameras directly, configuring codec (H.264),
and verifying camera connection even when ONVIF/RTSP are initially closed.
"""
import ctypes
from ctypes import c_int, c_uint, c_ulong, c_void_p, c_char_p, c_ushort, c_longlong, byref, cast, create_string_buffer
import os
import sys
import json
import urllib.parse
from typing import Optional, Dict, Any, Tuple
from core.logger import get_logger

log = get_logger()

# Dahua NetSDK Error Codes
NETSDK_ERRORS = {
    0: "Không có lỗi",
    1: "Sai mật khẩu (Password không đúng)",
    2: "Tài khoản người dùng không tồn tại",
    3: "Quá thời gian kết nối (Timeout - Kiểm tra IP hoặc mạng)",
    4: "Tài khoản đã đăng nhập ở nơi khác",
    5: "Tài khoản bị khóa do nhập sai mật khẩu nhiều lần",
    6: "Tài khoản nằm trong danh sách đen",
    7: "Thiết bị bận",
    8: "Không đủ quyền hạn",
    14: "Lỗi mạng hoặc camera không trực tuyến (Không kết nối được cổng 37777)",
    2147483647: "Lỗi không xác định",
}


class DahuaNetSDK:
    """Singleton wrapper for Dahua dhnetsdk.dll and dhconfigsdk.dll."""

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, dll_dir: Optional[str] = None):
        if hasattr(self, "_loaded"):
            return

        self._loaded = False
        self._sdk = None
        self._config_sdk = None
        self._init_handle = False
        self._dll_dir = dll_dir or self._find_dll_dir()

        self._load_dlls()

    def _find_dll_dir(self) -> str:
        """Find the directory containing Dahua win64 DLLs."""
        candidates = [
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "libs", "win64"),
            os.path.join(os.path.dirname(__file__), "..", "libs", "win64"),
            os.path.join(os.getcwd(), "PackStation", "libs", "win64"),
            os.path.join(os.getcwd(), "libs", "win64"),
            os.path.join("C:\\PackStation", "libs", "win64"),
            os.path.join("C:\\PackStation", "_internal", "libs", "win64"),
        ]
        for p in candidates:
            p_abs = os.path.abspath(p)
            if os.path.exists(os.path.join(p_abs, "dhnetsdk.dll")):
                return p_abs
        return os.path.abspath(candidates[0])

    def _load_dlls(self):
        """Load 64-bit dhnetsdk.dll and setup ctypes signatures."""
        if not os.path.exists(self._dll_dir):
            log.warning(f"[NetSDK] ⚠️ DLL directory not found: {self._dll_dir}")
            return

        dll_file = os.path.join(self._dll_dir, "dhnetsdk.dll")
        if not os.path.exists(dll_file):
            log.warning(f"[NetSDK] ⚠️ dhnetsdk.dll not found in {self._dll_dir}")
            return

        try:
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(self._dll_dir)

            self._sdk = ctypes.CDLL(dll_file)

            config_file = os.path.join(self._dll_dir, "dhconfigsdk.dll")
            if os.path.exists(config_file):
                self._config_sdk = ctypes.CDLL(config_file)

            # Setup function signatures
            # CLIENT_Init(cbDisConnect, dwUser) -> bool
            self._sdk.CLIENT_Init.argtypes = [c_void_p, c_ulong]
            self._sdk.CLIENT_Init.restype = ctypes.c_bool

            # CLIENT_Cleanup()
            self._sdk.CLIENT_Cleanup.argtypes = []
            self._sdk.CLIENT_Cleanup.restype = None

            # CLIENT_GetLastError() -> int
            self._sdk.CLIENT_GetLastError.argtypes = []
            self._sdk.CLIENT_GetLastError.restype = c_int

            # CLIENT_LoginEx2(ip, port, user, password, nSpecCap, pCapParam, lpDeviceInfo, error_code) -> LLONG
            self._sdk.CLIENT_LoginEx2.argtypes = [
                c_char_p, c_int, c_char_p, c_char_p,
                c_int, c_void_p, c_void_p, ctypes.POINTER(c_int)
            ]
            self._sdk.CLIENT_LoginEx2.restype = c_longlong

            # CLIENT_Logout(login_id) -> bool
            self._sdk.CLIENT_Logout.argtypes = [c_longlong]
            self._sdk.CLIENT_Logout.restype = ctypes.c_bool

            # CLIENT_GetNewDevConfig(login_id, szCommand, nChannel, szOutBuffer, dwOutBufferSize, error, waittime) -> bool
            self._sdk.CLIENT_GetNewDevConfig.argtypes = [
                c_longlong, c_char_p, c_int, c_char_p, c_uint, ctypes.POINTER(c_int), c_int
            ]
            self._sdk.CLIENT_GetNewDevConfig.restype = ctypes.c_bool

            # CLIENT_SetNewDevConfig(login_id, szCommand, nChannel, szInBuffer, dwInBufferSize, error, restart, waittime) -> bool
            self._sdk.CLIENT_SetNewDevConfig.argtypes = [
                c_longlong, c_char_p, c_int, c_char_p, c_uint, ctypes.POINTER(c_int), ctypes.POINTER(c_int), c_int
            ]
            self._sdk.CLIENT_SetNewDevConfig.restype = ctypes.c_bool

            self._loaded = True
            log.info(f"[NetSDK] ✅ Dahua NetSDK 64-bit loaded successfully from {self._dll_dir}")
        except Exception as e:
            log.error(f"[NetSDK] ❌ Error loading NetSDK: {e}")
            self._loaded = False

    @property
    def is_available(self) -> bool:
        """Check if NetSDK is successfully loaded."""
        return self._loaded and self._sdk is not None

    def init(self) -> bool:
        """Initialize the SDK."""
        if not self.is_available:
            return False
        if self._init_handle:
            return True
        try:
            ok = self._sdk.CLIENT_Init(None, 0)
            if ok:
                self._init_handle = True
                return True
        except Exception as e:
            log.error(f"[NetSDK] Init error: {e}")
        return False

    def cleanup(self):
        """Cleanup SDK resources."""
        if self.is_available and self._init_handle:
            try:
                self._sdk.CLIENT_Cleanup()
            except Exception:
                pass
            self._init_handle = False

    def get_last_error_message(self, err_code: Optional[int] = None) -> str:
        """Get readable error message from error code."""
        if err_code is None and self.is_available:
            try:
                err_code = self._sdk.CLIENT_GetLastError() & 0x7FFFFFFF
            except Exception:
                err_code = -1
        return NETSDK_ERRORS.get(err_code, f"Lỗi NetSDK mã #{err_code}")

    def login(self, ip: str, password: str, username: str = "admin", port: int = 37777) -> Tuple[int, str]:
        """Login to camera via Dahua NetSDK (Port 37777).

        Returns:
            (login_id, error_message) - login_id > 0 on success, 0 on failure.
        """
        if not self.init():
            return 0, "Không thể khởi tạo Dahua NetSDK DLL"

        device_info = create_string_buffer(1024)
        error_code = c_int(0)

        try:
            login_id = self._sdk.CLIENT_LoginEx2(
                ip.strip().encode("utf-8"),
                int(port),
                username.strip().encode("utf-8"),
                password.strip().encode("utf-8"),
                0,
                None,
                cast(device_info, c_void_p),
                byref(error_code)
            )

            if login_id != 0:
                return login_id, "Đăng nhập thành công"
            else:
                err_val = error_code.value & 0x7FFFFFFF
                msg = self.get_last_error_message(err_val)
                return 0, msg
        except Exception as e:
            return 0, f"Lỗi kết nối NetSDK: {e}"

    def logout(self, login_id: int) -> bool:
        """Logout from camera."""
        if not self.is_available or login_id == 0:
            return False
        try:
            return bool(self._sdk.CLIENT_Logout(login_id))
        except Exception:
            return False

    def get_codec(self, login_id: int, channel: int = 0) -> Optional[str]:
        """Get current video compression codec (H.264 or H.265) for channel."""
        if not self.is_available or login_id == 0:
            return None
        buf_size = 65536
        out_buf = create_string_buffer(buf_size)
        err = c_int(0)
        try:
            ok = self._sdk.CLIENT_GetNewDevConfig(
                login_id, b"Encode", channel,
                cast(out_buf, c_char_p), buf_size, byref(err), 5000
            )
            if ok:
                raw_str = out_buf.value.decode("utf-8", errors="ignore").strip().rstrip("\x00")
                data = json.loads(raw_str)
                codec = data["params"]["table"]["MainFormat"][0]["Video"]["Compression"]
                return str(codec)
        except Exception as e:
            log.error(f"[NetSDK] Error getting codec: {e}")
        return None

    def set_codec(self, login_id: int, target_codec: str = "H.264", channel: int = 0) -> Dict[str, Any]:
        """Ensure camera stream uses target codec (H.264 is best for RTSP/OpenCV)."""
        if not self.is_available or login_id == 0:
            return {"success": False, "error": "Chưa kết nối NetSDK"}

        buf_size = 65536
        out_buf = create_string_buffer(buf_size)
        err = c_int(0)

        try:
            # 1. Read existing config
            ok_get = self._sdk.CLIENT_GetNewDevConfig(
                login_id, b"Encode", channel,
                cast(out_buf, c_char_p), buf_size, byref(err), 5000
            )
            if not ok_get:
                err_code = self._sdk.CLIENT_GetLastError() & 0x7FFFFFFF
                return {"success": False, "error": f"Không đọc được cấu hình Encode (mã {err_code})"}

            raw_str = out_buf.value.decode("utf-8", errors="ignore").strip().rstrip("\x00")
            data = json.loads(raw_str)
            current_codec = data["params"]["table"]["MainFormat"][0]["Video"]["Compression"]

            if current_codec.upper() == target_codec.upper():
                return {"success": True, "old_codec": current_codec, "new_codec": target_codec, "changed": False}

            # 2. Modify codec to target
            data["params"]["table"]["MainFormat"][0]["Video"]["Compression"] = target_codec
            payload = json.dumps({"table": data["params"]["table"]}, ensure_ascii=False).encode("utf-8")
            in_buf = create_string_buffer(payload, len(payload))
            err_set = c_int(0)
            restart = c_int(0)

            # 3. Apply new config
            ok_set = self._sdk.CLIENT_SetNewDevConfig(
                login_id, b"Encode", channel,
                cast(in_buf, c_char_p), len(payload),
                byref(err_set), byref(restart), 5000
            )

            if ok_set:
                return {
                    "success": True,
                    "old_codec": current_codec,
                    "new_codec": target_codec,
                    "changed": True,
                    "restart_required": restart.value == 1
                }
            else:
                return {"success": False, "error": f"Lỗi thiết lập codec: {err_set.value}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def test_and_configure_camera(
        self,
        ip: str,
        password: str,
        username: str = "admin",
        port: int = 37777,
        optimize_codec: bool = True
    ) -> Dict[str, Any]:
        """Complete workflow: connects via port 37777, checks codec, optimizes to H.264,

        and returns verified RTSP URLs ready for packaging streaming.
        """
        result = {
            "success": False,
            "ip": ip,
            "port": port,
            "message": "",
            "codec": None,
            "rtsp_url_ch1": None,
            "rtsp_url_ch2": None,
        }

        login_id, msg = self.login(ip, password, username, port)
        if login_id == 0:
            result["message"] = f"❌ Kết nối Dahua NetSDK thất bại: {msg}"
            return result

        try:
            current_codec = self.get_codec(login_id, channel=0)
            result["codec"] = current_codec

            if optimize_codec and current_codec and current_codec.upper() == "H.265":
                codec_res = self.set_codec(login_id, "H.264", channel=0)
                if codec_res.get("success"):
                    result["codec"] = "H.264 (Đã tối ưu)"

            # Build safe RTSP URL with URL-encoded password
            # Use subtype=0 (main-stream) for QR scanning to work at ~1m distance
            pwd_quoted = urllib.parse.quote(password)
            rtsp1 = f"rtsp://{username}:{pwd_quoted}@{ip}:554/cam/realmonitor?channel=1&subtype=0"
            rtsp2 = f"rtsp://{username}:{pwd_quoted}@{ip}:554/cam/realmonitor?channel=2&subtype=0"

            result["success"] = True
            result["rtsp_url_ch1"] = rtsp1
            result["rtsp_url_ch2"] = rtsp2
            result["message"] = f"✅ Kết nối NetSDK thành công! Codec: {result['codec']}"
            return result
        finally:
            self.logout(login_id)
