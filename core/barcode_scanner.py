"""Barcode/QR scanner from camera frames using zxing-cpp + pyzbar + OpenCV fallback.

Optimized for weak hardware (i3 gen 5):
- ZXing C++ prioritized: 1-3ms scan time, ultra-low CPU, robust against skew/distortion
- Strict barcode format whitelist (Code128, Code39, Code93, QRCode, DataMatrix, EAN13) to prevent 6-digit phantom reads from empty camera noise
- Pyzbar and OpenCV QRCodeDetector as graceful fallbacks
- Extended cooldown for function codes (STOP, KETTHUC) to prevent repeated triggers
"""
import threading
import time
import cv2
import numpy as np
from typing import Callable, Optional

try:
    import zxingcpp
    HAS_ZXING = True
    _ZXING_FORMATS = (
        zxingcpp.BarcodeFormat.Code128
        | zxingcpp.BarcodeFormat.Code39
        | zxingcpp.BarcodeFormat.Code93
        | zxingcpp.BarcodeFormat.QRCode
        | zxingcpp.BarcodeFormat.DataMatrix
        | zxingcpp.BarcodeFormat.EAN13
    )
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


class BarcodeScanner:
    """Scans camera frames for barcodes/QR codes with ultra-fast C++ engines."""

    def __init__(self, on_code: Callable[[str, str], None] = None, interval_ms: int = 1000):
        self.on_code = on_code
        self.interval_ms = interval_ms
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame = None
        self._frame_lock = threading.Lock()
        self._last_code = ""
        self._last_code_time = 0
        self._cooldown_ms = 6000          # 6s cooldown between scans (Requirement 3)
        self._func_cooldown_ms = 6000     # 6s cooldown for function codes
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
    def is_valid_barcode(code_text: str, code_type: str = "") -> bool:
        """Filter out web URLs, ad links, promotional QR codes, and 6-digit camera noise phantom reads.
        
        Allows:
        1. 1D linear barcodes (Code 128, Code 39, EAN-13) for shipping tracking numbers.
        2. 2D QR codes containing actual shipping tracking numbers (Shopee SPX, TikTok, J&T, Viettel Post).
        3. Function commands (STOP, END, KETTHUC, DUNG, CANCEL, HUY, SETCA, MANUAL, DONTHUCONG, TC_).
        
        Rejects:
        1. Web URLs (http://, https://, ftp://, www., etc.)
        2. Promotional/ad domains (tiktok.com, tiktok.shop, shopee.vn, etc.)
        3. Noisy 1D symbologies (ITF / I25, UPC-E, EAN-8, Codabar, DataBar)
        4. Short pure-digit phantom numbers (< 8 digits, e.g. 6-digit noise) and non-function strings < 6 chars
        """
        text = (code_text or "").strip()
        if not text or len(text) < 2:
            return False

        lower = text.lower()
        # 1. Reject web URLs and link shorteners
        if lower.startswith(("http://", "https://", "ftp://", "www.")) or "://" in lower:
            return False

        # 2. Reject URLs with domain identifiers and query paths
        ad_indicators = (
            ".com", ".vn", ".shop", ".ee", ".ly",
            "tiktok.", "shopee.", "lazada.", "facebook.", "zalo."
        )
        if any(ind in lower for ind in ad_indicators) and ("/" in lower or "?" in lower):
            return False
        if any(d in lower for d in ("tiktok.com", "tiktok.shop", "shopee.vn", "shope.ee", "bit.ly", "tinyurl.com")):
            return False

        # 3. Check if this is a known system function code
        upper = text.upper()
        clean_alnum = "".join(ch for ch in upper if ch.isalnum())
        func_tokens = {
            "STOP", "END", "ENDTIME", "KETTHUC", "DUNG", "DUNGQUAY",
            "STOPORDER", "HOANTHANH", "TAMDUNG", "FINISH", "DONE",
            "CANCEL", "HUY", "HUYDON", "ABORT", "DELETE",
            "MANUAL", "DONTHUCONG", "THUCONG",
        }
        func_prefixes = (
            "KETTHUC", "STOP", "ENDTIME", "HUY", "CANCEL",
            "SETCA", "SHIFT", "DONTHUCONG", "TC_",
        )
        is_func = clean_alnum in func_tokens or upper.startswith(func_prefixes)

        if not is_func:
            # 4. Reject noisy 1D formats prone to 6-digit phantom reads on empty camera frames
            fmt_upper = (code_type or "").upper()
            noisy_formats = ("ITF", "I25", "UPCE", "UPC_E", "UPC-E", "EAN8", "EAN_8", "EAN-8", "CODABAR", "DATABAR")
            if any(nf in fmt_upper for nf in noisy_formats):
                return False

            # 5. Reject short pure-digit phantom numbers (< 8 digits, e.g. 6-digit noise) and short non-function strings (< 6 chars)
            if text.isdigit() and len(text) < 8:
                return False
            if len(text) < 6:
                return False

        return True

    def _scan_loop(self):
        while self._running:
            time.sleep(self.interval_ms / 1000.0)
            if not self._running:
                break

            with self._frame_lock:
                frame = self._frame

            if frame is None:
                continue

            now = time.time() * 1000
            # Skip CPU-heavy frame decoding if still within debounce cooldown
            if (now - self._last_code_time) < 1000:
                continue

            codes = self._detect(frame)
            for code_text, code_type in codes:
                if not self.is_valid_barcode(code_text, code_type):
                    continue

                upper = code_text.upper()
                is_func = any(k in upper for k in ["STOP", "END", "KETTHUC", "DUNG", "CANCEL", "HUY", "SETCA"])
                cooldown = self._func_cooldown_ms if is_func else self._cooldown_ms

                if (now - self._last_code_time) < cooldown:
                    continue

                self._last_code = code_text
                self._last_code_time = now

                if self.on_code:
                    self.on_code(code_text, code_type)

    def _detect(self, frame: np.ndarray) -> list[tuple[str, str]]:
        if frame is None or frame.size == 0:
            return []

        # Downscale ultra high-res frames (>1080p, e.g. 4K) to 1920 width to preserve full HD barcode detail
        h, w = frame.shape[:2]
        if w > 1920:
            scale = 1920.0 / w
            scan_frame = cv2.resize(frame, (1920, int(h * scale)), interpolation=cv2.INTER_AREA)
        else:
            scan_frame = frame

        # Convert to grayscale
        gray = cv2.cvtColor(scan_frame, cv2.COLOR_BGR2GRAY)
        results = []

        # 1. 🚀 Priority: ZXing C++ (10x faster, ~1-3ms CPU time, native binarization, strict format whitelist)
        if HAS_ZXING:
            try:
                decoded = zxingcpp.read_barcodes(gray, formats=_ZXING_FORMATS)
                for d in decoded:
                    text = d.text.strip()
                    fmt = str(d.format)
                    if text and self.is_valid_barcode(text, fmt):
                        results.append((text, fmt))
                return results
            except Exception:
                pass

        # 2. 🐢 Fallback: pyzbar (only when zxingcpp is unavailable; never use adaptiveThreshold noise amplifier)
        if not HAS_ZXING and HAS_PYZBAR:
            try:
                decoded = pyzbar_decode(gray, symbols=_PYZBAR_SYMBOLS)
                for d in decoded:
                    text = d.data.decode("utf-8", errors="replace").strip()
                    fmt = str(d.type)
                    if text and self.is_valid_barcode(text, fmt):
                        results.append((text, fmt))
                if results:
                    return results
            except Exception:
                pass

        # 3. 🔍 Fallback: OpenCV QRCodeDetector (only when C++ engines unavailable)
        if not HAS_ZXING and not HAS_PYZBAR:
            try:
                val, pts, _ = self._cv_qr.detectAndDecode(gray)
                if val and val.strip() and self.is_valid_barcode(val.strip(), "QRCODE"):
                    results.append((val.strip(), "QRCODE"))
            except Exception:
                pass

        return results
