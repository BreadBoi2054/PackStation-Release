"""Order Manager - handles order lifecycle (start → scan → end)."""
import os
import re
import time
import threading
from datetime import datetime
from typing import Callable, Optional
from core.logger import get_logger
from core.video_validation import check_video

log = get_logger()


class OrderManager:
    """Manages the full order lifecycle across scanner stations."""

    def __init__(self, db, config, video_recorder=None, audio_manager=None):
        self.db = db
        self.config = config
        self.video_recorder = video_recorder
        self.audio = audio_manager
        self._active_orders: dict[int, dict] = {}  # scanner_id -> order info
        self._finishing_orders: dict[int, dict] = {}  # scanner_id -> order info (recording final 8s)
        self._last_scan_times: dict[int, float] = {}  # scanner_id -> timestamp of last scan
        self.scan_cooldown_seconds: float = float(config.get("scan_cooldown_seconds", 6.0))
        self.end_delay_seconds: float = float(config.get("end_delay_seconds", 0.0))
        self._lock = threading.RLock()
        self.on_order_started: Optional[Callable] = None
        self.on_order_finishing: Optional[Callable] = None
        self.on_order_ended: Optional[Callable] = None
        self.on_duplicate: Optional[Callable] = None
        self.on_log: Optional[Callable] = None
        self.on_video_checked: Optional[Callable] = None
        self._load_active_orders()

    def _load_active_orders(self):
        """Restore active orders from DB on startup."""
        try:
            active = self.db.get_active_orders()
            for order in active:
                try:
                    dt = datetime.strptime(order["start_time"], "%Y-%m-%d %H:%M:%S")
                    start_ts = dt.timestamp()
                except Exception:
                    start_ts = time.time()

                self._active_orders[order["scanner_id"]] = {
                    "id": order["id"],
                    "order_sn": order["order_sn"],
                    "start_time": order["start_time"],
                    "start_timestamp": start_ts,
                }
        except Exception as e:
            log.error(f"[OrderManager] Load error: {e}")

    def _detect_function_code(self, code: str) -> tuple[str, str]:
        """
        Detect if a scanned code is a system function code.
        Returns:
            (func_type, meta)
            func_type in ["end", "cancel", "shift", "manual", "none"]
        """
        c = code.strip()
        if not c:
            return "none", ""

        c_upper = c.upper()
        # Clean alphanumeric for robust token matching
        c_clean = re.sub(r'[^A-Z0-9]', '', c_upper)

        fc = self.config.data.get("function_codes", {})
        end_prefix = self.config.get("end_code_prefix", "KETTHUC").upper()
        cancel_prefix = self.config.get("cancel_code_prefix", "HUYDON").upper()
        manual_prefix = self.config.get("manual_code_prefix", "DONTHUCONG").upper()
        shift_prefix = self.config.get("shift_code_prefix", "SETCA").upper()

        # 1. STOP / END CODES: Universal detection (STOP, ENDTIME, KETTHUC, DUNG, etc.)
        end_tokens = {
            "STOP", "END", "ENDTIME", "KETTHUC", "KET_THUC", "DUNG", "DUNGQUAY",
            "STOPORDER", "HOANTHANH", "TAMDUNG", "FINISH", "DONE"
        }
        if (c_clean in end_tokens or
            c_upper.startswith(end_prefix) or
            c_upper.startswith("STOP") or
            c_upper.startswith("KETTHUC") or
            c_upper.startswith("ENDTIME") or
            c_upper == fc.get("end_order", "END").upper()):
            return "end", c

        # 2. CANCEL CODES: Universal detection (CANCEL, HUYDON, HUY, ABORT)
        cancel_tokens = {"CANCEL", "HUY", "HUYDON", "HUY_DON", "ABORT", "DELETE"}
        if (c_clean in cancel_tokens or
            c_upper.startswith(cancel_prefix) or
            c_upper.startswith("HUY") or
            c_upper.startswith("CANCEL") or
            c_upper == fc.get("cancel_order", "CANCEL").upper()):
            return "cancel", c

        # 3. SHIFT / OPERATOR CODES: SETCA_Ca1, SHIFT_Huy, etc.
        if c_upper.startswith(shift_prefix) or c_upper.startswith("SHIFT"):
            prefix = shift_prefix if c_upper.startswith(shift_prefix) else "SHIFT"
            operator = c[len(prefix):].strip("_- :")
            return "shift", operator or "Ca 1"

        # 4. MANUAL ORDER CODES: DONTHUCONG, MANUAL
        if (c_clean in {"MANUAL", "DONTHUCONG", "THUCONG"} or
            c_upper.startswith(manual_prefix) or
            c_upper.startswith("DONTHUCONG") or
            c_upper == fc.get("manual_order", "MANUAL").upper()):
            return "manual", c

        return "none", ""

    def process_scan(self, code: str, scanner_id: int = 1, code_type: str = ""):
        """Process a scanned barcode - strictly differentiates function codes from orders."""
        code = code.strip()
        if not code:
            return

        # 🛡️ Filter out URLs, ads, and invalid non-function QR codes before cooldown
        from core.barcode_scanner import BarcodeScanner
        if not BarcodeScanner.is_valid_barcode(code, code_type):
            self._log(f"⚠️ Bỏ qua mã không hợp lệ (URL/quảng cáo/QR phụ): {code[:40]}", scanner_id)
            return

        # ⏱️ 6-second cooldown between any scans (Requirement 3)
        if self.scan_cooldown_seconds > 0:
            with self._lock:
                now = time.time()
                last_time = self._last_scan_times.get(scanner_id, 0)
                if (now - last_time) < self.scan_cooldown_seconds:
                    rem = self.scan_cooldown_seconds - (now - last_time)
                    self._log(f"⏳ Giãn cách quét {int(self.scan_cooldown_seconds)} giây: Vui lòng chờ {rem:.1f}s nữa", scanner_id)
                    return
                self._last_scan_times[scanner_id] = now

        func_type, meta = self._detect_function_code(code)

        # 🛑 Function code: End order (Requirement 4: extra 8 seconds recording)
        if func_type == "end":
            self.db.add_scan_log(code, scanner_id, "function_code")
            with self._lock:
                has_active = scanner_id in self._active_orders
                is_finishing = scanner_id in self._finishing_orders

            if is_finishing:
                self._log("⏳ Đơn hàng đang quay nốt các giây kết thúc...", scanner_id)
                return

            if has_active:
                if self.end_delay_seconds > 0:
                    self._start_delayed_end_order(scanner_id, delay_seconds=self.end_delay_seconds)
                else:
                    self._end_current_order(scanner_id, "completed")
            else:
                self._log("ℹ️ Quét mã dừng: Không có đơn hàng nào đang ghi hình", scanner_id)
                if self.audio:
                    self.audio.play("end")
            return

        # ❌ Function code: Cancel order (immediate cancel)
        if func_type == "cancel":
            self.db.add_scan_log(code, scanner_id, "function_code")
            with self._lock:
                has_active = scanner_id in self._active_orders or scanner_id in self._finishing_orders

            if has_active:
                self._end_current_order(scanner_id, "cancelled")
            else:
                self._log("ℹ️ Quét mã hủy: Không có đơn hàng nào đang ghi hình", scanner_id)
                if self.audio:
                    self.audio.play("cancel")
            return

        # 👤 Function code: Set shift/operator
        if func_type == "shift":
            operator = meta
            self.config.set("current_shift", operator)
            self.db.add_scan_log(code, scanner_id, "function_code")
            self._log(f"👤 Ca làm việc: {operator}", scanner_id)
            if self.audio:
                self.audio.play("start")
            return

        # 📦 Function code: Manual packaging order (when barcode is unreadable)
        if func_type == "manual":
            manual_sn = f"TC_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self._start_order(manual_sn, scanner_id)
            return

        # 🏷️ Regular order barcode (Shopee, Lazada, TikTok tracking number)
        # CRITICAL: Function codes NEVER reach this line!
        self._start_order(code, scanner_id)

    def _start_delayed_end_order(self, scanner_id: int, delay_seconds: float = 8.0):
        """Record for an extra delay_seconds (8s) before finalizing video (Requirement 4)."""
        with self._lock:
            order_info = self._active_orders.pop(scanner_id, None)
            if not order_info:
                return
            order_sn = order_info["order_sn"]
            order_id = order_info["id"]
            self._finishing_orders[scanner_id] = order_info

        self._log(f"⏳ Đã quét mã dừng! Tiếp tục quay thêm {int(delay_seconds)} giây để hoàn tất đơn {order_sn}...", scanner_id)
        if self.audio:
            self.audio.play("start")  # Feedback audio confirmation

        if self.on_order_finishing:
            self.on_order_finishing(order_sn, scanner_id, delay_seconds)

        def _delayed_worker(target_order_id: int):
            time.sleep(delay_seconds)
            self._end_current_order(scanner_id, "completed", expected_order_id=target_order_id)

        threading.Thread(target=_delayed_worker, args=(order_id,), daemon=True, name="DelayedStopWorker").start()

    def force_start_order(self, order_sn: str, scanner_id: int = 1):
        """Force start an order, bypassing duplicate check (e.g. worker re-recording)."""
        self._start_order(order_sn, scanner_id, force=True)

    def _start_order(self, order_sn: str, scanner_id: int, force: bool = False):
        """Start a new packaging order atomically to prevent race conditions."""
        with self._lock:
            active_order = self._active_orders.get(scanner_id)
            is_finishing = scanner_id in self._finishing_orders

            if is_finishing:
                finishing_sn = self._finishing_orders[scanner_id].get("order_sn", "")
                self._log(f"⏳ Đơn {finishing_sn} đang quay nốt 8s cuối, vui lòng đợi xong trước khi quét đơn mới!", scanner_id)
                if self.audio:
                    self.audio.play("duplicate")
                return

            if active_order:
                current_sn = active_order.get("order_sn", "")
                if current_sn == order_sn:
                    self._log(f"⚠️ Đơn {order_sn} đang được ghi hình rồi!", scanner_id)
                else:
                    self._log(f"⛔ Đang đóng đơn {current_sn}! Quét mã DỪNG để hoàn tất trước khi quét đơn mới.", scanner_id)
                if self.audio:
                    self.audio.play("duplicate")
                return

            # Check for duplicate if not forced
            if not force:
                cooldown = self.config.get("duplicate_cooldown_seconds", 60)
                if self.db.check_duplicate(order_sn, cooldown):
                    if self.on_duplicate:
                        self.on_duplicate(order_sn, scanner_id)
                    self._log(f"⚠️ Đơn trùng: {order_sn}", scanner_id)
                    if self.audio:
                        self.audio.play("duplicate")
                    return

            # Ensure station doesn't already have an active order in SQLite
            db_active = self.db.get_active_order(scanner_id)
            if db_active:
                active_sn = db_active["order_sn"]
                self._log(f"⛔ Bàn {scanner_id} đã có đơn {active_sn} đang ghi hình trong CSDL!", scanner_id)
                if self.audio:
                    self.audio.play("duplicate")
                return

            # Start new order in DB atomically while holding lock
            operator = self.config.get("current_shift", "")
            order_id = self.db.start_order(order_sn, scanner_id, operator)
            self.db.add_scan_log(order_sn, scanner_id, "barcode", order_id)

            cams = self.config.get_station_cameras(scanner_id)
            channels = [i + 1 for i, c in enumerate(cams) if c.strip()] or [1]
            self._active_orders[scanner_id] = {
                "id": order_id,
                "order_sn": order_sn,
                "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "start_timestamp": time.time(),
                "channels": channels,
            }

        # Start recording asynchronously (non-blocking, outside lock)
        if self.video_recorder and self.config.get("auto_record"):
            for ch in channels:
                self.db.set_video_check(order_id, ch, "recording", "Đang ghi hình")
                try:
                    self.video_recorder.start_recording(order_sn, channel=ch)
                except Exception as exc:
                    self.db.set_video_check(order_id, ch, "missing", f"Không bắt đầu ghi: {exc}")
                    log.error(f"[Order] Start recording error ch{ch}: {exc}")

        if self.audio:
            self.audio.play("start")

        if self.on_order_started:
            self.on_order_started(order_sn, scanner_id, order_id)

        log_msg = f"🔄 Quay lại đơn: {order_sn}" if force else f"✅ Bắt đầu: {order_sn}"
        self._log(log_msg, scanner_id)

    def _end_current_order(self, scanner_id: int, status: str = "completed", expected_order_id: Optional[int] = None):
        """End the current active order for a scanner station."""
        with self._lock:
            if expected_order_id is not None:
                # Timer task bound to a specific order_id
                finishing = self._finishing_orders.get(scanner_id)
                active = self._active_orders.get(scanner_id)
                if finishing and finishing.get("id") == expected_order_id:
                    order_info = self._finishing_orders.pop(scanner_id, None)
                elif active and active.get("id") == expected_order_id:
                    order_info = self._active_orders.pop(scanner_id, None)
                else:
                    # Target order was already ended or cancelled; do not touch new order!
                    return
            else:
                order_info = self._active_orders.pop(scanner_id, None)
                if not order_info:
                    order_info = self._finishing_orders.pop(scanner_id, None)
                else:
                    self._finishing_orders.pop(scanner_id, None)

        if not order_info:
            return

        order_sn = order_info["order_sn"]
        order_id = order_info["id"]

        self.db.end_order(order_id, status)

        # Stop recording asynchronously with automatic DB video registration callback
        if self.video_recorder:
            channels = order_info.get("channels") or [1]
            start_ts = order_info.get("start_timestamp", time.time())
            calc_duration = max(1.0, round(time.time() - start_ts, 1))
            for ch in channels:
                def _create_db_callback(o_id, channel_num, dur):
                    def _on_video_saved(filepath, size):
                        try:
                            if not self.db.order_exists(o_id):
                                log.info(f"[Order] ℹ️ Bỏ qua lưu video cho đơn ID={o_id} ({order_sn}) vì đơn đã bị xóa.")
                                return
                            health = self.video_recorder.get_recording_health(order_sn, channel_num)
                            check_status, check_message, actual_duration = check_video(filepath, dur, health)
                            if not self.db.set_video_check(o_id, channel_num, check_status, check_message, health.get("dropped", 0)):
                                return
                            if check_status != "ok":
                                self._log(f"⚠️ Video Cam {channel_num} đơn {order_sn}: {check_message}", scanner_id)
                            if filepath and size > 0:
                                video_id = self.db.add_video(
                                    o_id, os.path.basename(filepath), filepath, channel_num
                                )
                                if video_id:
                                    self.db.update_video_info(video_id, size, actual_duration)
                            if self.on_video_checked and self.db.order_exists(o_id):
                                self.on_video_checked(o_id)
                        except Exception as e:
                            log.error(f"[Order] Video check error: {e}")
                            if self.db.order_exists(o_id):
                                self.db.set_video_check(o_id, channel_num, "corrupt", str(e))
                    return _on_video_saved

                self.video_recorder.stop_recording(
                    order_sn, ch, on_complete=_create_db_callback(order_id, ch, calc_duration)
                )

        if self.audio:
            self.audio.play("end" if status == "completed" else "cancel")

        if self.on_order_ended:
            self.on_order_ended(order_sn, scanner_id, status)

        emoji = "✅" if status == "completed" else "❌"
        self._log(f"{emoji} Kết thúc: {order_sn} ({status})", scanner_id)

    def get_active_order(self, scanner_id: int = 1) -> Optional[dict]:
        with self._lock:
            if scanner_id in self._finishing_orders:
                return self._finishing_orders[scanner_id]
            return self._active_orders.get(scanner_id)

    def is_finishing(self, scanner_id: int = 1) -> bool:
        with self._lock:
            return scanner_id in self._finishing_orders

    def get_active_or_finishing_order_ids(self) -> set:
        """Return set of order IDs currently in packing or finishing state across all stations."""
        with self._lock:
            ids = {info["id"] for info in self._active_orders.values() if info and "id" in info}
            ids.update(info["id"] for info in self._finishing_orders.values() if info and "id" in info)
            return ids

    def is_order_active_or_finishing(self, order_id: int) -> bool:
        return order_id in self.get_active_or_finishing_order_ids()

    def check_timeouts(self):
        """Check if any active order exceeded max recording duration and auto-stop it."""
        max_minutes = self.config.get("max_record_duration_minutes", 10)
        try:
            max_minutes = int(max_minutes)
        except (ValueError, TypeError):
            max_minutes = 10

        if max_minutes <= 0:
            return  # 0 = unlimited

        max_seconds = max_minutes * 60
        now = time.time()

        with self._lock:
            active_items = list(self._active_orders.items())

        for scanner_id, order_info in active_items:
            start_ts = order_info.get("start_timestamp", 0)
            if start_ts > 0 and (now - start_ts) >= max_seconds:
                order_sn = order_info["order_sn"]
                order_id = order_info.get("id")
                log.info(f"[Order] ⏰ Timeout auto-stop ({max_minutes}m) for order: {order_sn}")
                self._end_current_order(scanner_id, "completed", expected_order_id=order_id)
                self._log(f"⏰ Tự động dừng quay: Đơn {order_sn} đã đạt giới hạn tối đa {max_minutes} phút", scanner_id)

    def _log(self, message: str, scanner_id: int = 1):
        if self.on_log:
            self.on_log(message, scanner_id)
        log.info(f"[Order] {message}")
