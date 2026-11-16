"""Barcode/QR scanner from camera frames using zxing-cpp + pyzbar + OpenCV fallback.

Optimized for weak hardware (i3 gen 5) & personal overhead camera workflow:
- ZXing C++ prioritized: 1-3ms scan time, ultra-low CPU, robust against skew/distortion
- Strict barcode format whitelist (Code128, Code39, Code93, QRCode, DataMatrix, EAN13)
- State-aware filtering: when packing, only look for STOP/CANCEL cards; when idle, ignore STOP/CANCEL cards
- Motion-assisted cadence (~0.2s pickup when hands/parcels move, 0% idle CPU when floor is static)
- Carrier tracking priority ranking for multi-barcode Shopee/TikTok/J&T/GHN shipping labels
"""
import re
import threading
import time
from typing import Callable, Optional

import cv2
import numpy as np

try:
    import zxingcpp
    HAS_ZXING = True
    _ZXING_FORMAT_LIST = [
        zxingcpp.BarcodeFormat.Code128,
        zxingcpp.BarcodeFormat.Code39,
        zxingcpp.BarcodeFormat.Code93,
        zxingcpp.BarcodeFormat.QRCode,
        zxingcpp.BarcodeFormat.DataMatrix,
        zxingcpp.BarcodeFormat.EAN13,
    ]
    if hasattr(zxingcpp, "BarcodeFormats"):
        _ZXING_FORMATS = zxingcpp.BarcodeFormats(_ZXING_FORMAT_LIST)
    else:
        _ZXING_FORMATS = _ZXING_FORMAT_LIST[0]
        for _fmt in _ZXING_FORMAT_LIST[1:]:
            _ZXING_FORMATS = _ZXING_FORMATS | _fmt
except ImportError:
    HAS_ZXING = False
    _ZXING_FORMATS = None

try:
    from pyzbar.pyzbar import decode as pyzbar_decode, ZBarSymbol
    HAS_PYZBAR = True
    _PYZBAR_SYMBOLS = [
        ZBarSymbol.CODE128,
        ZBarSymbol.CODE39,
        ZBarSymbol.CODE93,
        ZBarSymbol.QRCODE,
        ZBarSymbol.EAN13,
    ]
except ImportError:
    HAS_PYZBAR = False
    _PYZBAR_SYMBOLS = None

_END_TOKENS = {
    "STOP", "END", "ENDTIME", "KETTHUC", "DUNG", "DUNGQUAY",
    "STOPORDER", "HOANTHANH", "TAMDUNG", "FINISH", "DONE",
}
_CANCEL_TOKENS = {"CANCEL", "HUY", "HUYDON", "ABORT", "DELETE"}
_MANUAL_TOKENS = {"MANUAL", "DONTHUCONG", "THUCONG"}

_END_RE = re.compile(r"^(KETTHUC|STOP|ENDTIME)([_\-:\s].*)?$")
_CANCEL_RE = re.compile(r"^(HUYDON|HUY_DON|CANCEL)([_\-:\s].*)?$")
_SHIFT_RE = re.compile(r"^(SETCA.*|SHIFT([_\-:\s].+|\d+.*))$")
_MANUAL_RE = re.compile(r"^DONTHUCONG([_\-:\s].*)?$")

_CARRIER_PATTERNS = (
    re.compile(r"^SPXVN[A-Z0-9]{8,20}$"),                    # Shopee Express
    re.compile(r"^VN[0-9]{9,15}[A-Z0-9]*$"),                  # VNPost / Shopee
    re.compile(r"^(8[0-9]{11,14}|JT[0-9]{10,15})$"),          # TikTok Shop / J&T Express
    re.compile(r"^(G[A-Z0-9]{7,14}|GY[A-Z0-9]{6,14})$"),      # GHN
    re.compile(r"^LEX[A-Z0-9]{8,20}$"),                       # Lazada Express
    re.compile(r"^VTP[A-Z0-9]{8,18}$"),                       # Viettel Post
    re.compile(r"^S[0-9]+\.[A-Z0-9.\-]{6,25}$"),              # GHTK
)


class BarcodeScanner:
    """Scans camera frames for barcodes/QR codes with ultra-fast C++ engines."""

    def __init__(
        self,
        on_code: Callable[[str, str], None] = None,
        interval_ms: int = 1000,
        is_packing: Optional[Callable[[], bool]] = None,
    ):
        self.on_code = on_code
        self.interval_ms = interval_ms
        self.is_packing = is_packing
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame = None
        self._frame_lock = threading.Lock()
        self._last_code = ""
        self._last_code_time = 0
        self._cooldown_ms = 6000
        self._func_cooldown_ms = 6000
        self._cv_qr = cv2.QRCodeDetector()

    @property
    def available(self) -> bool:
        return HAS_ZXING or HAS_PYZBAR or True

    def set_frame(self, frame: np.ndarray):
        with self._frame_lock:
            self._frame = frame

    def start(self):
        if self._running or not self.available:
            return
        self._running = True
        self._thread = threading.Thread(target=self._scan_loop, daemon=True, name="BarcodeScannerThread")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    @staticmethod
    def classify_function_code(code_text: str) -> str:
        """Classify system function QR codes without false-matching normal orders like HUYHOANG123."""
        c = (code_text or "").strip()
        if not c:
            return "none"
        c_upper = c.upper()
        c_clean = re.sub(r"[^A-Z0-9]", "", c_upper)

        if c_clean in _END_TOKENS or _END_RE.match(c_upper):
            return "end"
        if c_clean in _CANCEL_TOKENS or _CANCEL_RE.match(c_upper):
            return "cancel"
        if _SHIFT_RE.match(c_upper):
            return "shift"
        if c_clean in _MANUAL_TOKENS or _MANUAL_RE.match(c_upper):
            return "manual"
        return "none"

    @classmethod
    def score_barcode(cls, code_text: str, code_type: str = "") -> int:
        """Rank barcodes detected in the same frame so carrier waybills beat routing codes and SKUs."""
        text = (code_text or "").strip()
        if not text:
            return 0
        if cls.classify_function_code(text) != "none":
            return 100

        # Product retail barcodes (e.g. Vietnamese 893... EAN-13) must never outrank shipping waybills
        fmt_upper = (code_type or "").upper()
        if "EAN13" in fmt_upper or "EAN_13" in fmt_upper or "EAN-13" in fmt_upper:
            return 25

        upper = text.upper()
        for pat in _CARRIER_PATTERNS:
            if pat.match(upper):
                return 90

        # Hub sorting / routing codes typically contain multiple dashes (e.g. HN-SOC-02-A1)
        if text.count("-") >= 2:
            return 15

        if "128" in fmt_upper and len(text) >= 10:
            return 70

        return 50

    @classmethod
    def is_valid_barcode(cls, code_text: str, code_type: str = "") -> bool:
        """Filter out web URLs, ad links, promotional QR codes, and 6-digit camera noise phantom reads."""
        text = (code_text or "").strip()
        if not text or len(text) < 2:
            return False

        lower = text.lower()
        if lower.startswith(("http://", "https://", "ftp://", "www.")) or "://" in lower:
            return False

        ad_indicators = (
            ".com", ".vn", ".shop", ".ee", ".ly",
            "tiktok.", "shopee.", "lazada.", "facebook.", "zalo.",
        )
        if any(ind in lower for ind in ad_indicators) and ("/" in lower or "?" in lower):
            return False
        if any(d in lower for d in ("tiktok.com", "tiktok.shop", "shopee.vn", "shope.ee", "bit.ly", "tinyurl.com")):
            return False

        upper = text.upper()
        is_func = cls.classify_function_code(text) != "none" or upper.startswith("TC_")

        if not is_func:
            fmt_upper = (code_type or "").upper()
            noisy_formats = ("ITF", "I25", "UPCE", "UPC_E", "UPC-E", "EAN8", "EAN_8", "EAN-8", "CODABAR", "DATABAR")
            if any(nf in fmt_upper for nf in noisy_formats):
                return False

            if text.isdigit() and len(text) < 8:
                return False
            if len(text) < 6:
                return False

        return True

    def _scan_loop(self):
        last_frame_obj = None
        prev_thumb = None
        last_full_scan_ms = 0.0

        while self._running:
            tick_s = min(0.2, max(0.05, self.interval_ms / 1000.0))
            time.sleep(tick_s)
            if not self._running:
                break

            with self._frame_lock:
                frame = self._frame

            if frame is None or frame is last_frame_obj or getattr(frame, "size", 0) == 0:
                continue
            last_frame_obj = frame

            now = time.time() * 1000.0
            # Motion-gated decode: scan fast (~200ms) when motion occurs, stay near 0% CPU when table is static
            try:
                thumb = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_NEAREST)
                thumb_gray = cv2.cvtColor(thumb, cv2.COLOR_BGR2GRAY) if thumb.ndim == 3 else thumb
                if prev_thumb is not None and prev_thumb.shape == thumb_gray.shape:
                    diff = float(np.mean(cv2.absdiff(thumb_gray, prev_thumb)))
                    if diff < 1.8 and (now - last_full_scan_ms) < max(200, self.interval_ms):
                        continue
                prev_thumb = thumb_gray
            except Exception:
                pass
            last_full_scan_ms = now

            codes = self._detect(frame)
            if not codes:
                continue

            currently_packing = bool(self.is_packing()) if self.is_packing is not None else None

            for code_text, code_type in codes:
                func_kind = self.classify_function_code(code_text)

                # State-aware filtering:
                # - While packing, ignore parcel barcodes/SKUs so lying labels never trigger duplicate locks
                # - While idle, ignore KETTHUC/HUYDON left sitting on the stand
                if currently_packing is True and func_kind not in ("end", "cancel"):
                    continue
                if currently_packing is False and func_kind in ("end", "cancel"):
                    continue

                is_func = func_kind != "none"
                base_cooldown = self._func_cooldown_ms if is_func else self._cooldown_ms
                effective_cooldown = base_cooldown if code_text == self._last_code else min(150, base_cooldown)

                if (now - self._last_code_time) < effective_cooldown:
                    continue

                self._last_code = code_text
                self._last_code_time = now

                if self.on_code:
                    self.on_code(code_text, code_type)
                break

    def _detect(self, frame: np.ndarray) -> list[tuple[str, str]]:
        if frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        if w > 1920:
            scale = 1920.0 / w
            scan_frame = cv2.resize(frame, (1920, int(h * scale)), interpolation=cv2.INTER_AREA)
        else:
            scan_frame = frame

        gray = cv2.cvtColor(scan_frame, cv2.COLOR_BGR2GRAY) if scan_frame.ndim == 3 else scan_frame
        results = []

        if HAS_ZXING:
            try:
                decoded = zxingcpp.read_barcodes(gray, formats=_ZXING_FORMATS)
                for d in decoded:
                    text = d.text.strip()
                    fmt = str(d.format)
                    if text and self.is_valid_barcode(text, fmt):
                        results.append((text, fmt))
                results.sort(key=lambda item: self.score_barcode(item[0], item[1]), reverse=True)
                return results
            except Exception:
                pass

        if not HAS_ZXING and HAS_PYZBAR:
            try:
                decoded = pyzbar_decode(gray, symbols=_PYZBAR_SYMBOLS)
                for d in decoded:
                    text = d.data.decode("utf-8", errors="replace").strip()
                    fmt = str(d.type)
                    if text and self.is_valid_barcode(text, fmt):
                        results.append((text, fmt))
                if results:
                    results.sort(key=lambda item: self.score_barcode(item[0], item[1]), reverse=True)
                    return results
            except Exception:
                pass

        if not HAS_ZXING and not HAS_PYZBAR:
            try:
                val, _, _ = self._cv_qr.detectAndDecode(gray)
                if val and val.strip() and self.is_valid_barcode(val.strip(), "QRCODE"):
                    results.append((val.strip(), "QRCODE"))
            except Exception:
                pass

        results.sort(key=lambda item: self.score_barcode(item[0], item[1]), reverse=True)
        return results
