"""Unit tests for individual PackStation modules."""
import os
import sys
import time
import unittest
import tempfile
import shutil
import json
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database
from config import Config
from core.video_recorder import VideoRecorder
from core.order_manager import OrderManager


class TestBarcodeScanner(unittest.TestCase):
    """Unit tests for barcode_scanner.py"""

    def setUp(self):
        from core.barcode_scanner import BarcodeScanner
        self.detected_codes = []
        self.scanner = BarcodeScanner(
            on_code=lambda code, ctype: self.detected_codes.append((code, ctype)),
            interval_ms=100
        )

    def tearDown(self):
        self.scanner.stop()

    def test_available_always_true(self):
        self.assertTrue(self.scanner.available)

    def test_start_stop_lifecycle(self):
        self.assertFalse(self.scanner._running)
        self.scanner.start()
        self.assertTrue(self.scanner._running)
        self.scanner.stop()
        self.assertFalse(self.scanner._running)

    def test_set_frame_thread_safe(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.scanner.set_frame(frame)
        with self.scanner._frame_lock:
            self.assertIsNotNone(self.scanner._frame)

    def test_detect_empty_frame_returns_empty(self):
        result = self.scanner._detect(np.array([]))
        self.assertEqual(result, [])

    def test_detect_none_frame_returns_empty(self):
        result = self.scanner._detect(None)
        self.assertEqual(result, [])

    def test_cooldown_prevents_duplicate(self):
        """Same code within cooldown period should be ignored."""
        self.scanner._last_code = "TEST123"
        self.scanner._last_code_time = time.time() * 1000  # now
        self.scanner._cooldown_ms = 2000
        # Simulate scanning same code
        self.scanner.start()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.scanner.set_frame(frame)
        time.sleep(0.3)
        self.scanner.stop()
        # No duplicate should be detected from blank frame
        self.assertEqual(len(self.detected_codes), 0)

    def test_downscale_large_frame(self):
        """Frames wider than 1920px should be downscaled."""
        large_frame = np.zeros((2160, 3840, 3), dtype=np.uint8)
        # Should not raise
        result = self.scanner._detect(large_frame)
        self.assertIsInstance(result, list)


class TestVideoRecorder(unittest.TestCase):
    """Unit tests for video_recorder.py"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        from core.video_recorder import VideoRecorder
        self.recorder = VideoRecorder(self.tmp_dir, fps=10, resolution=(320, 240))

    def tearDown(self):
        self.recorder.stop_all()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_start_creates_file(self):
        filepath = self.recorder.start_recording("TEST_001", channel=1)
        self.assertTrue(filepath.endswith(".mp4"))
        self.assertTrue(self.recorder.is_recording("TEST_001", 1))

    def test_stop_returns_filepath(self):
        self.recorder.start_recording("TEST_002", channel=1)
        filepath = self.recorder.stop_recording("TEST_002", 1)
        self.assertIsNotNone(filepath)
        self.assertFalse(self.recorder.is_recording("TEST_002", 1))

    def test_write_frame_enqueues(self):
        self.recorder.start_recording("TEST_003", channel=1)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        self.recorder.write_frame("TEST_003", frame, channel=1)
        time.sleep(0.2)  # Let worker process
        self.recorder.stop_recording("TEST_003", 1)

    def test_stop_all_terminates_worker(self):
        self.recorder.start_recording("TEST_004", channel=1)
        self.recorder.stop_all()
        self.assertFalse(self.recorder._running)

    def test_dual_channel_recording(self):
        fp1 = self.recorder.start_recording("DUAL_TEST", channel=1)
        fp2 = self.recorder.start_recording("DUAL_TEST", channel=2)
        self.assertIn("Cam1", fp1)
        self.assertIn("Cam2", fp2)
        self.assertTrue(self.recorder.is_recording("DUAL_TEST", 1))
        self.assertTrue(self.recorder.is_recording("DUAL_TEST", 2))

    def test_frame_queue_maxsize(self):
        """Verify 30-frame buffering limit enforced by BoundedSemaphore."""
        slots = []
        for _ in range(30):
            slots.append(self.recorder._frame_slots.acquire(blocking=False))
        self.assertTrue(all(slots), "Should be able to acquire exactly 30 frame slots")
        self.assertFalse(self.recorder._frame_slots.acquire(blocking=False), "31st acquire should fail (max 30 slots)")
        for _ in range(30):
            self.recorder._frame_slots.release()

    def test_cleanup_old_videos_retention_days(self):
        from datetime import date, timedelta
        # Create folder 40 days ago, 10 days ago, and today
        day40 = (date.today() - timedelta(days=40)).isoformat()
        day10 = (date.today() - timedelta(days=10)).isoformat()
        day2 = (date.today() - timedelta(days=2)).isoformat()

        p40 = os.path.join(self.recorder.video_dir, day40)
        p10 = os.path.join(self.recorder.video_dir, day10)
        p2 = os.path.join(self.recorder.video_dir, day2)

        os.makedirs(p40, exist_ok=True)
        os.makedirs(p10, exist_ok=True)
        os.makedirs(p2, exist_ok=True)

        # Cleanup with 30 days retention: p40 deleted, p10 & p2 kept
        self.recorder.cleanup_old_videos(retention_days=30)
        self.assertFalse(os.path.exists(p40))
        self.assertTrue(os.path.exists(p10))
        self.assertTrue(os.path.exists(p2))

        # Cleanup with safety floor (passing 2 days must clamp to 7 days floor)
        self.recorder.cleanup_old_videos(retention_days=2)
        # p10 (10 days old) should be deleted (< 7 days cutoff)
        self.assertFalse(os.path.exists(p10))
        # p2 (2 days old) MUST be kept because retention minimum is 7 days!
        self.assertTrue(os.path.exists(p2))

    def test_duplicate_order_incremental_filename(self):
        fp1 = self.recorder.start_recording("RE_RECORD_TEST", channel=1)
        # Create dummy file to simulate existing recording
        with open(fp1, "wb") as f:
            f.write(b"data")
        self.recorder.stop_recording("RE_RECORD_TEST", 1)

        # Second recording for same order
        fp2 = self.recorder.start_recording("RE_RECORD_TEST", channel=1)
        self.assertIn("Lan2", fp2)
        self.recorder.stop_recording("RE_RECORD_TEST", 1)


class TestDatabase(unittest.TestCase):
    """Unit tests for database.py"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        from database import Database
        self.db = Database(self.db_path)
        self.db.initialize()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_wal_mode(self):
        mode = self.db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode, "wal")

    def test_start_order(self):
        order_id = self.db.start_order("SN_001", 1, "TestOp")
        self.assertIsNotNone(order_id)
        self.assertGreater(order_id, 0)

    def test_end_order(self):
        order_id = self.db.start_order("SN_002")
        self.db.end_order(order_id, "completed")
        active = self.db.get_active_order(1)
        self.assertIsNone(active)

    def test_duplicate_detection(self):
        self.db.start_order("SN_DUP")
        is_dup = self.db.check_duplicate("SN_DUP", cooldown_seconds=60)
        self.assertTrue(is_dup)
        is_dup2 = self.db.check_duplicate("SN_NEW", cooldown_seconds=60)
        self.assertFalse(is_dup2)

    def test_crash_recovery(self):
        self.db.start_order("CRASH_001")
        self.db.start_order("CRASH_002")
        recovered = self.db.recover_crashed_orders()
        self.assertEqual(recovered, 2)
        # Should be 0 on second call
        recovered2 = self.db.recover_crashed_orders()
        self.assertEqual(recovered2, 0)

    def test_add_scan_log(self):
        self.db.add_scan_log("CODE123", 1, "barcode")
        scans = self.db.get_recent_scans(10)
        self.assertGreater(len(scans), 0)

    def test_add_video(self):
        order_id = self.db.start_order("VID_TEST")
        video_id = self.db.add_video(order_id, "test.mp4", "/path/test.mp4", 1)
        self.assertGreater(video_id, 0)
        videos = self.db.get_order_videos(order_id)
        self.assertEqual(len(videos), 1)

    def test_today_count(self):
        self.db.start_order("COUNT_001")
        self.db.start_order("COUNT_002")
        count = self.db.get_today_count()
        self.assertGreaterEqual(count, 2)

    def test_get_orders_in_range(self):
        from datetime import date
        self.db.start_order("RANGE_001")
        today = date.today().isoformat()
        orders = self.db.get_orders_in_range(today, today)
        self.assertGreater(len(orders), 0)

    def test_get_all_orders(self):
        self.db.start_order("ALL_001")
        self.db.start_order("ALL_002")
        orders = self.db.get_all_orders(limit=10)
        self.assertGreaterEqual(len(orders), 2)

    def test_get_videos_by_order_sn(self):
        order_id = self.db.start_order("VID_SN_TEST")
        self.db.add_video(order_id, "sn_test.mp4", "/path/sn_test.mp4", 1)
        videos = self.db.get_videos_by_order_sn("VID_SN_TEST")
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["filename"], "sn_test.mp4")

    def test_delete_order(self):
        order_id = self.db.start_order("DEL_TEST_01")
        vid_file = os.path.join(self.tmp_dir, "del_test.mp4")
        with open(vid_file, "w") as f:
            f.write("dummy")
        self.db.add_video(order_id, "del_test.mp4", vid_file, 1)
        self.db.add_scan_log("DEL_TEST_01", 1, "barcode", order_id)
        self.db.end_order(order_id, status="completed")

        self.assertIsNotNone(self.db.conn.execute("SELECT id FROM orders WHERE id=?", (order_id,)).fetchone())
        self.assertTrue(os.path.exists(vid_file))

        del_files = self.db.delete_order(order_id, delete_video_files=True)
        self.assertEqual(len(del_files), 1)
        self.assertFalse(os.path.exists(vid_file))
        self.assertIsNone(self.db.conn.execute("SELECT id FROM orders WHERE id=?", (order_id,)).fetchone())
        self.assertEqual(len(self.db.get_order_videos(order_id)), 0)


class TestOrderManager(unittest.TestCase):
    """Unit tests for order_manager.py"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        from database import Database
        from config import Config
        self.db = Database(os.path.join(self.tmp_dir, "test.db"))
        self.db.initialize()
        self.config = Config(self.tmp_dir)
        from core.order_manager import OrderManager
        self.om = OrderManager(self.db, self.config)
        self.om.scan_cooldown_seconds = 0
        self.om.end_delay_seconds = 0
        self.log_messages = []
        self.om.on_log = lambda msg, sid: self.log_messages.append(msg)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_process_scan_starts_order(self):
        self.om.process_scan("ORDER_001")
        active = self.om.get_active_order(1)
        self.assertIsNotNone(active)
        self.assertEqual(active["order_sn"], "ORDER_001")

    def test_process_scan_end_code(self):
        self.om.process_scan("ORDER_002")
        self.om.process_scan("KETTHUC")
        active = self.om.get_active_order(1)
        self.assertIsNone(active)

    def test_process_scan_cancel_code(self):
        self.om.process_scan("ORDER_003")
        self.om.process_scan("HUYDON")
        active = self.om.get_active_order(1)
        self.assertIsNone(active)

    def test_process_scan_shift_code(self):
        self.om.process_scan("SETCANguyen")
        shift = self.config.get("current_shift")
        self.assertEqual(shift, "Nguyen")

    def test_duplicate_rejected(self):
        self.om.process_scan("DUP_ORDER")
        self.om.process_scan("STOP")
        self.om.process_scan("DUP_ORDER")  # Should be rejected as duplicate
        dup_logs = [m for m in self.log_messages if "trùng" in m]
        self.assertGreater(len(dup_logs), 0)

    def test_force_start_order_bypasses_duplicate(self):
        self.om.process_scan("DUP_ORDER_2")
        self.om.process_scan("STOP")
        self.om.process_scan("DUP_ORDER_2")  # Rejected
        # Force start must bypass duplicate check and start active order
        self.om.force_start_order("DUP_ORDER_2")
        active = self.om.get_active_order(1)
        self.assertIsNotNone(active)
        self.assertEqual(active["order_sn"], "DUP_ORDER_2")

    def test_empty_scan_ignored(self):
        self.om.process_scan("")
        self.om.process_scan("   ")
        active = self.om.get_active_order(1)
        self.assertIsNone(active)

    def test_stop_code_idle_does_not_start_order(self):
        """CRITICAL: Scanning STOP, ENDTIME, DUNG, KETTHUC when idle MUST NOT start an order!"""
        for code in ["STOP", "stop", "ENDTIME", "DUNG", "KETTHUC", "KET_THUC", "END"]:
            self.om.process_scan(code)
            active = self.om.get_active_order(1)
            self.assertIsNone(active, f"Code '{code}' incorrectly started an order when idle!")

    def test_stop_code_universal_ends_active_order(self):
        """Universal stop codes (STOP, ENDTIME, DUNG, etc.) end an active order."""
        for code in ["STOP", "ENDTIME", "DUNG", "KETTHUC"]:
            self.om.process_scan(f"ORDER_{code}")
            active = self.om.get_active_order(1)
            self.assertIsNotNone(active)
            self.om.process_scan(code)
            active_after = self.om.get_active_order(1)
            self.assertIsNone(active_after, f"Code '{code}' failed to end active order!")

    def test_cancel_code_idle_does_not_start_order(self):
        """Scanning CANCEL, HUY, HUYDON when idle MUST NOT start an order."""
        for code in ["CANCEL", "HUY", "HUYDON", "HUY_DON"]:
            self.om.process_scan(code)
            active = self.om.get_active_order(1)
            self.assertIsNone(active, f"Cancel code '{code}' incorrectly started an order when idle!")

    def test_check_timeouts_auto_stops_order(self):
        """Active order exceeding max_record_duration_minutes is automatically stopped."""
        self.config.set("max_record_duration_minutes", 5)  # 5 minutes
        self.om.process_scan("TIMEOUT_TEST_001")
        active = self.om.get_active_order(1)
        self.assertIsNotNone(active)

        # Simulate 6 minutes having passed (360 seconds)
        active["start_timestamp"] = time.time() - 360

        self.om.check_timeouts()
        active_after = self.om.get_active_order(1)
        self.assertIsNone(active_after, "Order was not auto-stopped after exceeding timeout!")
        self.assertTrue(any("Tự động dừng quay" in m for m in self.log_messages))

    def test_check_timeouts_keeps_active_order_within_limit(self):
        """Active order within max_record_duration_minutes remains active."""
        self.config.set("max_record_duration_minutes", 10)  # 10 minutes
        self.om.process_scan("NORMAL_ORDER_002")
        active = self.om.get_active_order(1)
        self.assertIsNotNone(active)

        # Simulate 2 minutes passed (120 seconds)
        active["start_timestamp"] = time.time() - 120

        self.om.check_timeouts()
        active_after = self.om.get_active_order(1)
        self.assertIsNotNone(active_after, "Order was prematurely stopped while within timeout!")

    def test_order2_blocked_while_order1_active(self):
        """Scanning Order 2 while Order 1 is active must be blocked until STOP is scanned."""
        self.om.process_scan("ORDER_FIRST")
        self.assertEqual(self.om.get_active_order(1)["order_sn"], "ORDER_FIRST")

        # Scanning second order while first is packing: MUST BE BLOCKED
        self.om.process_scan("ORDER_SECOND")
        self.assertEqual(self.om.get_active_order(1)["order_sn"], "ORDER_FIRST")
        blocked_logs = [m for m in self.log_messages if "Đang đóng đơn" in m and "ORDER_FIRST" in m]
        self.assertGreater(len(blocked_logs), 0)

        # Scanning stop finishes order 1
        self.om.process_scan("STOP")
        self.assertIsNone(self.om.get_active_order(1))

        # Now scanning second order succeeds
        self.om.process_scan("ORDER_SECOND")
        self.assertEqual(self.om.get_active_order(1)["order_sn"], "ORDER_SECOND")

    def test_scan_cooldown_enforced(self):
        """Every scan must enforce scan_cooldown_seconds interval."""
        self.om.scan_cooldown_seconds = 6.0
        self.om.process_scan("ORDER_COOL1")
        self.assertEqual(self.om.get_active_order(1)["order_sn"], "ORDER_COOL1")

        # Immediate next scan within 6s is blocked
        self.om.process_scan("STOP")
        self.assertEqual(self.om.get_active_order(1)["order_sn"], "ORDER_COOL1")
        self.assertTrue(any("Giãn cách quét" in m for m in self.log_messages))

        # Simulate 7 seconds passed
        self.om._last_scan_times[1] = time.time() - 7.0
        self.om.process_scan("STOP")
        self.assertIsNone(self.om.get_active_order(1))

    def test_delayed_end_order(self):
        """Scanning stop code triggers finishing state and delay before finalization."""
        self.om.end_delay_seconds = 0.15
        self.om.process_scan("ORDER_DELAY")
        self.om.process_scan("STOP")

        # Immediately after STOP, order should be in finishing state
        self.assertTrue(self.om.is_finishing(1))
        # Scanning another order during this delay is blocked
        self.om.process_scan("ORDER_NEW_DELAY")
        self.assertTrue(any("đang quay nốt" in m for m in self.log_messages))

        # Wait for delay to complete
        time.sleep(0.25)
        self.assertFalse(self.om.is_finishing(1))
        self.assertIsNone(self.om.get_active_order(1))


class TestConfig(unittest.TestCase):
    """Unit tests for config.py"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        from config import Config
        self.config = Config(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_default_values(self):
        self.assertEqual(self.config.get("auto_scan_interval_ms"), 1000)
        self.assertTrue(self.config.get("auto_scan_enabled"))

    def test_set_and_get(self):
        self.config.set("test_key", "test_value")
        self.assertEqual(self.config.get("test_key"), "test_value")

    def test_save_and_reload(self):
        self.config.set("persist_key", 42)
        self.config.save()
        from config import Config
        config2 = Config(self.tmp_dir)
        self.assertEqual(config2.get("persist_key"), 42)


class TestLogger(unittest.TestCase):
    """Unit tests for logger.py"""

    def test_logger_singleton(self):
        from core.logger import get_logger
        log1 = get_logger()
        log2 = get_logger()
        self.assertIs(log1, log2)

    def test_logger_writes_to_file(self):
        from core.logger import get_logger
        log = get_logger()
        log.info("UNIT_TEST_MARKER_12345")
        # Check log file exists
        for handler in log.handlers:
            if hasattr(handler, 'baseFilename'):
                self.assertTrue(os.path.exists(handler.baseFilename))


class TestI18n(unittest.TestCase):
    """Unit tests for i18n.py"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp_dir, "i18n"), exist_ok=True)
        test_lang = {"hello": "Xin chào", "greeting": "Chào {name}!"}
        with open(os.path.join(self.tmp_dir, "i18n", "vi-VN.json"), "w", encoding="utf-8") as f:
            json.dump(test_lang, f)
        from i18n import I18n
        self.i18n = I18n("vi-VN", os.path.join(self.tmp_dir, "i18n"))

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_translation(self):
        self.assertEqual(self.i18n.t("hello"), "Xin chào")

    def test_missing_key_returns_key(self):
        self.assertEqual(self.i18n.t("nonexistent"), "nonexistent")

    def test_template_substitution(self):
        result = self.i18n.t("greeting", name="Duy")
        self.assertEqual(result, "Chào Duy!")


class TestAudioManager(unittest.TestCase):
    """Unit tests for audio_manager.py"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        from core.audio_manager import AudioManager
        self.audio = AudioManager(self.tmp_dir, enabled=True)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_default_sounds_created(self):
        for filename in self.audio.SOUNDS.values():
            filepath = os.path.join(self.tmp_dir, filename)
            self.assertTrue(os.path.exists(filepath), f"Missing: {filename}")

    def test_disabled_no_play(self):
        self.audio.enabled = False
        # Should not raise
        self.audio.play("start")


class TestVideoLocator(unittest.TestCase):
    """Test locating video file for orders (both existing and moved/deleted)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        from database import Database
        from config import Config
        self.db = Database(os.path.join(self.tmp_dir, "test.db"))
        self.db.initialize()
        self.config = Config(self.tmp_dir)
        self.config.set("video_dir", os.path.join(self.tmp_dir, "Videos"))

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_locate_video_file_found_and_not_found(self):
        from ui.app_window import AppWindow
        from datetime import date
        order_id = self.db.start_order("LOCATE_TEST_001")
        self.db.end_order(order_id, "completed")
        order = self.db.get_today_orders()[0]

        class DummyApp:
            def __init__(self, db, config):
                self.db = db
                self.config = config
            _locate_order_video_file = AppWindow._locate_order_video_file
            _locate_order_video_files = AppWindow._locate_order_video_files

        dummy = DummyApp(self.db, self.config)
        # 1. When video does not exist
        self.assertIsNone(dummy._locate_order_video_file(order))

        # 2. When video exists in video_dir / date / order_sn.mp4
        today = date.today().isoformat()
        date_dir = os.path.join(self.config.get("video_dir"), today)
        os.makedirs(date_dir, exist_ok=True)
        vid_file = os.path.join(date_dir, "LOCATE_TEST_001_Cam1.mp4")
        with open(vid_file, "w") as f:
            f.write("dummy")

        located = dummy._locate_order_video_file(order)
        self.assertEqual(located, vid_file)

        # 3. When re-recorded _Lan2 exists, it returns _Lan2
        time.sleep(0.01)
        vid_file2 = os.path.join(date_dir, "LOCATE_TEST_001_Cam1_Lan2.mp4")
        with open(vid_file2, "w") as f:
            f.write("dummy lan 2")
        located2 = dummy._locate_order_video_file(order)
        self.assertEqual(located2, vid_file2)


class TestBarcodeFilter(unittest.TestCase):
    """Test URL and QR filtering for shipping barcodes vs ads/routing."""

    def test_url_rejection(self):
        from core.barcode_scanner import BarcodeScanner
        urls = [
            "https://seller-vn.tiktok.com/promotion",
            "http://tiktok.com",
            "https://vt.tiktok.com/ZSNxxxx",
            "www.tiktok.com/something",
            "https://shopee.vn/product/123",
            "http://bit.ly/3xyz",
        ]
        for url in urls:
            self.assertFalse(
                BarcodeScanner.is_valid_barcode(url, "BarcodeFormat.QRCode"),
                f"Failed to reject URL: {url}"
            )
            self.assertFalse(
                BarcodeScanner.is_valid_barcode(url, "BarcodeFormat.Code128"),
                f"Failed to reject URL with 1D format: {url}"
            )

    def test_qr_tracking_allowed(self):
        from core.barcode_scanner import BarcodeScanner
        # Shopee SPX, TikTok J&T, Viettel Post tracking QR codes must be accepted
        tracking_qrs = [
            "SPXVN066035959139",     # Shopee SPX QR from user photo 3
            "862443605627",          # J&T QR from user photo 1
            "VTPVN9043413698",       # Viettel Post QR from user photo 2
            "VN1234567890",
        ]
        for qr in tracking_qrs:
            self.assertTrue(
                BarcodeScanner.is_valid_barcode(qr, "BarcodeFormat.QRCode"),
                f"Failed to allow valid tracking QR: {qr}"
            )
            self.assertTrue(
                BarcodeScanner.is_valid_barcode(qr, "QRCODE"),
                f"Failed to allow valid tracking QRCODE: {qr}"
            )

    def test_function_qr_allowed(self):
        from core.barcode_scanner import BarcodeScanner
        func_codes = ["STOP", "KETTHUC", "END", "DUNG", "HUY", "CANCEL", "HUYDON", "SETCA_Ca1", "MANUAL"]
        for fc in func_codes:
            self.assertTrue(
                BarcodeScanner.is_valid_barcode(fc, "BarcodeFormat.QRCode"),
                f"Failed to allow function QR: {fc}"
            )

    def test_1d_tracking_barcodes_allowed(self):
        from core.barcode_scanner import BarcodeScanner
        real_barcodes = [
            "862443605627",          # J&T from user photo 1
            "VTPVN9043413698",       # Viettel Post from user photo 2
            "SPXVN066035959139",     # Shopee SPX from user photo 3
            "VN1234567890",
        ]
        for bc in real_barcodes:
            self.assertTrue(
                BarcodeScanner.is_valid_barcode(bc, "BarcodeFormat.Code128"),
                f"Failed to allow 1D barcode: {bc}"
            )
            self.assertTrue(
                BarcodeScanner.is_valid_barcode(bc, "MANUAL"),
                f"Failed to allow manual entry: {bc}"
            )
            self.assertTrue(
                BarcodeScanner.is_valid_barcode(bc, ""),
                f"Failed to allow untyped barcode: {bc}"
            )

    def test_order_mgr_ignores_urls_and_allows_shopee_qr(self):
        import tempfile
        import shutil
        from database import Database
        from config import Config
        from core.video_recorder import VideoRecorder
        from core.order_manager import OrderManager

        tmp_dir = tempfile.mkdtemp()
        try:
            db = Database(os.path.join(tmp_dir, "test.db"))
            db.initialize()
            config = Config(tmp_dir)
            recorder = VideoRecorder(tmp_dir)
            om = OrderManager(db, config, recorder)
            om.scan_cooldown_seconds = 0

            # Scan a TikTok URL - MUST BE REJECTED
            om.process_scan("https://seller-vn.tiktok.com/offer", scanner_id=1, code_type="BarcodeFormat.QRCode")
            self.assertEqual(len(om._active_orders), 0)

            # Scan TikTok promo URL from actual user photo 2 - MUST BE REJECTED
            om.process_scan("https://m.tiktok.shop/s/ALIfL0VLNKnL", scanner_id=1, code_type="BarcodeFormat.QRCode")
            self.assertEqual(len(om._active_orders), 0)

            # Scan real Shopee QR tracking number - MUST BE ACCEPTED
            om.process_scan("SPXVN066035959139", scanner_id=1, code_type="BarcodeFormat.QRCode")
            self.assertEqual(len(om._active_orders), 1)
            self.assertEqual(om._active_orders[1]["order_sn"], "SPXVN066035959139")

            db.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_delayed_stop_cancellation_does_not_stop_new_order(self):
        """Test Requirement 1: If delayed stop is cancelled and a new order starts, the old timer must NOT stop the new order."""
        import tempfile
        tmp_dir = tempfile.mkdtemp()
        try:
            db = Database(os.path.join(tmp_dir, "test.db"))
            db.initialize()
            cfg = Config(tmp_dir)
            rec = VideoRecorder(tmp_dir)
            om = OrderManager(db, cfg, rec)
            om.scan_cooldown_seconds = 0
            om.end_delay_seconds = 0.2  # 200ms delay

            # 1. Start Order A
            om.process_scan("ORDER_A", scanner_id=1)
            self.assertEqual(om.get_active_order(1)["order_sn"], "ORDER_A")
            order_a_id = om.get_active_order(1)["id"]

            # 2. Trigger delayed end for Order A
            om.process_scan("KETTHUC", scanner_id=1)
            self.assertTrue(om.is_finishing(1))

            # 3. Cancel Order A while finishing
            om.process_scan("HUYDON", scanner_id=1)
            self.assertIsNone(om.get_active_order(1))
            self.assertFalse(om.is_finishing(1))

            # 4. Start Order B on the same station immediately
            om.process_scan("ORDER_B", scanner_id=1)
            active_b = om.get_active_order(1)
            self.assertIsNotNone(active_b)
            self.assertEqual(active_b["order_sn"], "ORDER_B")
            order_b_id = active_b["id"]
            self.assertNotEqual(order_a_id, order_b_id)

            # 5. Wait for the old delayed timer (200ms) to trigger
            time.sleep(0.4)

            # 6. Verify Order B is STILL ACTIVE and packing, not terminated by old timer!
            current = om.get_active_order(1)
            self.assertIsNotNone(current, "Order B should still be active!")
            self.assertEqual(current["order_sn"], "ORDER_B")
            self.assertEqual(current["id"], order_b_id)

            # Verify in DB: Order A is cancelled, Order B is still packing
            order_a_row = db.conn.execute("SELECT status FROM orders WHERE id=?", (order_a_id,)).fetchone()
            order_b_row = db.conn.execute("SELECT status FROM orders WHERE id=?", (order_b_id,)).fetchone()
            self.assertEqual(order_a_row["status"], "cancelled")
            self.assertEqual(order_b_row["status"], "packing")

            rec.stop_all()
            db.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_concurrent_scans_single_packing_order(self):
        """Test Requirement 2: Simultaneous scans must result in exactly one packing order per station."""
        import tempfile
        import threading
        tmp_dir = tempfile.mkdtemp()
        try:
            db = Database(os.path.join(tmp_dir, "test.db"))
            db.initialize()
            cfg = Config(tmp_dir)
            rec = VideoRecorder(tmp_dir)
            om = OrderManager(db, cfg, rec)
            om.scan_cooldown_seconds = 0

            barrier = threading.Barrier(10)
            results = []

            def _scan_worker(idx):
                code = f"CONCURRENT_SN_{idx}"
                barrier.wait()  # Release all 10 threads simultaneously
                om.process_scan(code, scanner_id=1)

            threads = [threading.Thread(target=_scan_worker, args=(i,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Verify: Only 1 active order in OrderManager
            self.assertIsNotNone(om.get_active_order(1))

            # Verify: In database, exactly 1 order for station 1 has status 'packing'
            packing_orders = db.conn.execute(
                "SELECT * FROM orders WHERE scanner_id=1 AND status='packing'"
            ).fetchall()
            self.assertEqual(len(packing_orders), 1, f"Expected exactly 1 packing order, found: {len(packing_orders)}")

            rec.stop_all()
            db.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_pin_protection_and_camera_masking(self):
        """Test Requirement 3: Manager PIN verification and RTSP URL password masking."""
        import tempfile
        tmp_dir = tempfile.mkdtemp()
        try:
            cfg = Config(tmp_dir)
            self.assertFalse(cfg.is_pin_set())
            self.assertTrue(cfg.verify_pin("anything"))  # No PIN set -> True

            # Set PIN
            cfg.set_pin("8888")
            self.assertTrue(cfg.is_pin_set())
            self.assertTrue(cfg.verify_pin("8888"))
            self.assertFalse(cfg.verify_pin("1234"))

            # Clear PIN
            cfg.set_pin("")
            self.assertFalse(cfg.is_pin_set())

            # Test RTSP URL credential masking
            url = "rtsp://admin:SecretPass123@192.168.1.100:554/cam/realmonitor?channel=1&subtype=0"
            masked = Config.mask_rtsp_url(url)
            self.assertNotIn("SecretPass123", masked)
            self.assertIn("******", masked)
            self.assertIn("admin:", masked)
            self.assertIn("@192.168.1.100:554", masked)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_sync_videos_multi_day_distinct_orders(self):
        """Test Requirement 4: Videos with identical order_sn on different days create distinct orders."""
        import tempfile
        tmp_dir = tempfile.mkdtemp()
        try:
            db = Database(os.path.join(tmp_dir, "test.db"))
            db.initialize()

            # Create 2 video files on 2 different day directories
            day1_dir = os.path.join(tmp_dir, "2026-09-10")
            day2_dir = os.path.join(tmp_dir, "2026-10-10")
            os.makedirs(day1_dir, exist_ok=True)
            os.makedirs(day2_dir, exist_ok=True)

            with open(os.path.join(day1_dir, "REUSED_SN_Cam1.mp4"), "wb") as f:
                f.write(b"data1")
            with open(os.path.join(day2_dir, "REUSED_SN_Cam1.mp4"), "wb") as f:
                f.write(b"data2")

            result = db.sync_videos_from_folder(tmp_dir)
            self.assertEqual(result["total_files"], 2)
            self.assertEqual(result["orders_created"], 2)

            # Verify in DB: 2 orders exist with same order_sn but different dates
            orders = db.conn.execute("SELECT id, order_sn, start_time FROM orders WHERE order_sn='REUSED_SN'").fetchall()
            self.assertEqual(len(orders), 2)
            dates = {o["start_time"][:10] for o in orders}
            self.assertEqual(dates, {"2026-09-10", "2026-10-10"})

            # Verify each video is linked to its correct date order
            for o in orders:
                vids = db.get_order_videos(o["id"])
                self.assertEqual(len(vids), 1)
                vid_path = vids[0]["filepath"]
                self.assertIn(o["start_time"][:10], vid_path)

            db.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_cleanup_old_videos_updates_sqlite(self):
        """Test Requirement 4: cleanup_old_videos cleans physical files and removes SQLite records."""
        import tempfile
        from datetime import date, timedelta
        tmp_dir = tempfile.mkdtemp()
        try:
            db = Database(os.path.join(tmp_dir, "test.db"))
            db.initialize()
            rec = VideoRecorder(tmp_dir, db=db)

            # Create an old folder (45 days ago)
            old_date = (date.today() - timedelta(days=45)).isoformat()
            old_dir = os.path.join(tmp_dir, old_date)
            os.makedirs(old_dir, exist_ok=True)
            old_video = os.path.join(old_dir, "OLD_ORDER_Cam1.mp4")
            with open(old_video, "wb") as f:
                f.write(b"video_bytes")

            order_id = db.start_order("OLD_ORDER", 1)
            db.add_video(order_id, "OLD_ORDER_Cam1.mp4", old_video, 1)

            # Verify video in DB before cleanup
            self.assertEqual(len(db.get_order_videos(order_id)), 1)

            # Run cleanup with 30 days retention
            rec.cleanup_old_videos(retention_days=30)

            # Verify folder deleted from disk
            self.assertFalse(os.path.exists(old_video))
            # Verify SQLite record was also cleaned up
            self.assertEqual(len(db.get_order_videos(order_id)), 0)

            rec.stop_all()
            db.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_updater_version_comparison_and_data_safety(self):
        """Test Auto-Updater version comparison, SQLite online WAL backup, and protection of DB/config/Videos."""
        import tempfile
        from core.updater import (
            backup_user_data,
            create_and_run_updater_script,
            is_newer_version,
            parse_version,
            strip_protected_items,
        )

        self.assertEqual(parse_version("v1.5.4"), (1, 5, 4))
        self.assertEqual(parse_version("1.5.4.0"), (1, 5, 4))
        self.assertTrue(is_newer_version("v1.5.5", "v1.5.4"))
        self.assertTrue(is_newer_version("v2.0.0", "v1.5.4"))
        self.assertFalse(is_newer_version("v1.5.4", "v1.5.4"))
        self.assertFalse(is_newer_version("v1.5.3", "v1.5.4"))

        tmp_dir = tempfile.mkdtemp()
        try:
            # 1. Test backup_user_data with a real SQLite WAL database
            db_file = os.path.join(tmp_dir, "packstation.db")
            db = Database(db_file)
            db.initialize()
            db.start_order("UPD_ORDER_01", 1)
            db.close()

            cfg_file = os.path.join(tmp_dir, "packstation-config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                f.write('{"station_name": "Ban 1"}')

            backup_res = backup_user_data(tmp_dir)
            self.assertTrue(backup_res["ok"])
            self.assertEqual(len(backup_res["backups"]), 2)
            for b in backup_res["backups"]:
                self.assertTrue(os.path.exists(b))

            # 2. Test strip_protected_items removes DB, config, Videos, logs from staged folder
            staged = os.path.join(tmp_dir, "staged")
            os.makedirs(os.path.join(staged, "Videos"), exist_ok=True)
            os.makedirs(os.path.join(staged, "logs"), exist_ok=True)
            os.makedirs(os.path.join(staged, "_internal"), exist_ok=True)
            with open(os.path.join(staged, "packstation.db"), "wb") as f:
                f.write(b"empty_release_db")
            with open(os.path.join(staged, "packstation-config.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(staged, "PackStation.exe"), "wb") as f:
                f.write(b"new_exe_binary")

            strip_protected_items(staged)
            self.assertFalse(os.path.exists(os.path.join(staged, "packstation.db")))
            self.assertFalse(os.path.exists(os.path.join(staged, "packstation-config.json")))
            self.assertFalse(os.path.exists(os.path.join(staged, "Videos")))
            self.assertFalse(os.path.exists(os.path.join(staged, "logs")))
            self.assertTrue(os.path.exists(os.path.join(staged, "PackStation.exe")))

            # 3. Test updater script generation without launching
            bat_path = create_and_run_updater_script(staged, tmp_dir, launch_after=False, restart_app=False)
            self.assertTrue(os.path.exists(bat_path))
            with open(bat_path, "r", encoding="utf-8") as f:
                bat_text = f.read()
            self.assertIn("robocopy", bat_text)
            self.assertIn("packstation.db", bat_text)
            self.assertIn("packstation-config.json", bat_text)
            self.assertIn("GEQ 8", bat_text)
            self.assertIn(":rollback", bat_text)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_sqlite_wal_uncheckpointed_backup_and_failure_abort(self):
        """Test Requirement 1: SQLite Backup API captures uncheckpointed WAL transactions and aborts on corrupt DB."""
        import sqlite3
        import tempfile
        from core.updater import backup_sqlite_database, backup_user_data

        tmp_dir = tempfile.mkdtemp()
        try:
            db_path = os.path.join(tmp_dir, "packstation.db")
            db = Database(db_path)
            db.initialize()
            # Disable auto-checkpoint so writes remain in the -wal file
            db.conn.execute("PRAGMA wal_autocheckpoint=0")
            db.start_order("WAL_UNCHECKPOINTED_001", 1)
            db.start_order("WAL_UNCHECKPOINTED_002", 1)

            wal_file = db_path + "-wal"
            self.assertTrue(os.path.exists(wal_file))
            self.assertGreater(os.path.getsize(wal_file), 0)

            # While db connection is still open and WAL is NOT checkpointed, run backup_sqlite_database
            backup_path = os.path.join(tmp_dir, "packstation_wal_backup.db")
            res = backup_sqlite_database(db_path, backup_path)
            self.assertTrue(res["ok"], f"Backup failed: {res.get('error')}")
            self.assertTrue(os.path.exists(backup_path))

            # Open backup in isolated connection and verify uncheckpointed WAL rows are present
            bak_conn = sqlite3.connect(backup_path)
            rows = bak_conn.execute("SELECT order_sn FROM orders ORDER BY id").fetchall()
            bak_conn.close()
            order_sns = [r[0] for r in rows]
            self.assertIn("WAL_UNCHECKPOINTED_001", order_sns)
            self.assertIn("WAL_UNCHECKPOINTED_002", order_sns)
            db.close()

            # Test corrupt database causes backup_user_data to fail and abort update
            corrupt_dir = os.path.join(tmp_dir, "corrupt_env")
            os.makedirs(corrupt_dir, exist_ok=True)
            with open(os.path.join(corrupt_dir, "packstation.db"), "wb") as f:
                f.write(b"NOT_A_VALID_SQLITE_HEADER_CORRUPT_DATA_1234567890")
            bad_res = backup_user_data(corrupt_dir)
            self.assertFalse(bad_res["ok"])
            self.assertIn("thất bại", bad_res["error"])
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_update_package_rejects_source_only_zip_and_zipball(self):
        """Test Requirement 2: Reject source-only ZIP (missing PackStation.exe), zipball URLs, and checksum mismatches."""
        import hashlib
        import pathlib
        import tempfile
        import zipfile
        from core.updater import (
            download_and_stage_update,
            get_update_mode,
            is_trusted_download_url,
            validate_portable_package,
        )

        # 1. Source zipball URLs and untrusted domains must be rejected
        self.assertFalse(
            is_trusted_download_url("https://api.github.com/repos/BreadBoi2054/PackStation-Release/zipball/v1.5.5")
        )
        self.assertFalse(is_trusted_download_url("https://evil.example.com/PackStation.zip"))
        self.assertTrue(
            is_trusted_download_url(
                "https://github.com/BreadBoi2054/PackStation-Release/releases/download/v1.5.5/PackStation-v1.5.5-Windows.zip"
            )
        )

        tmp_dir = tempfile.mkdtemp()
        try:
            # 2. Separate source_git mode vs portable mode
            src_mode_dir = os.path.join(tmp_dir, "src_repo")
            os.makedirs(os.path.join(src_mode_dir, ".git"), exist_ok=True)
            self.assertEqual(get_update_mode(src_mode_dir), "source_git")

            portable_mode_dir = os.path.join(tmp_dir, "portable_app")
            os.makedirs(portable_mode_dir, exist_ok=True)
            with open(os.path.join(portable_mode_dir, "PackStation.exe"), "wb") as f:
                f.write(b"MZ_FAKE_EXE")
            self.assertEqual(get_update_mode(portable_mode_dir), "portable")

            # 3. Create a source-only ZIP (no PackStation.exe) -> must be rejected!
            src_zip_path = os.path.join(tmp_dir, "source_only.zip")
            with zipfile.ZipFile(src_zip_path, "w") as zf:
                zf.writestr("PackStation-main/main.py", "print('hello')")
                zf.writestr("PackStation-main/config.py", "DEFAULTS = {}")

            src_zip_url = pathlib.Path(src_zip_path).as_uri()
            stage_res = download_and_stage_update(src_zip_url, portable_mode_dir)
            self.assertFalse(stage_res["ok"])
            self.assertIn("PackStation.exe", stage_res["error"])

            # 4. Create a valid portable ZIP and verify checksum validation
            valid_zip_path = os.path.join(tmp_dir, "PackStation-v1.5.6-Windows.zip")
            with zipfile.ZipFile(valid_zip_path, "w") as zf:
                zf.writestr("PackStation/PackStation.exe", "MZ_NEW_EXE_V156")
                zf.writestr("PackStation/_internal/python314.dll", "DLL_BYTES")
                zf.writestr("PackStation/i18n/vi-VN.json", "{}")

            with open(valid_zip_path, "rb") as f:
                zip_bytes = f.read()
            true_sha = hashlib.sha256(zip_bytes).hexdigest()
            valid_url = pathlib.Path(valid_zip_path).as_uri()

            # Wrong SHA-256 must be rejected
            bad_sha_res = download_and_stage_update(
                valid_url, portable_mode_dir, expected_sha256="0" * 64
            )
            self.assertFalse(bad_sha_res["ok"])
            self.assertIn("SHA-256", bad_sha_res["error"])

            # Correct SHA-256 and size must succeed
            good_res = download_and_stage_update(
                valid_url,
                portable_mode_dir,
                expected_size=len(zip_bytes),
                expected_sha256=true_sha,
            )
            self.assertTrue(good_res["ok"], f"Expected success, got: {good_res.get('error')}")
            ok_pkg, _ = validate_portable_package(good_res["staged_dir"])
            self.assertTrue(ok_pkg)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_portable_updater_batch_execution_and_rollback_in_isolated_temp(self):
        """Test Requirement 3: Run updater_apply.bat in isolated temp dir; verify update preserves DB/WAL/config/Videos and rolls back on failure."""
        import subprocess
        import tempfile
        from core.updater import create_and_run_updater_script

        tmp_dir = tempfile.mkdtemp()
        try:
            target_dir = os.path.join(tmp_dir, "app")
            staged_dir = os.path.join(tmp_dir, "app", "temp_update", "extracted", "PackStation")
            os.makedirs(os.path.join(target_dir, "_internal"), exist_ok=True)
            os.makedirs(os.path.join(target_dir, "Videos", "2026-10-17"), exist_ok=True)
            os.makedirs(os.path.join(target_dir, "logs"), exist_ok=True)
            os.makedirs(os.path.join(staged_dir, "_internal"), exist_ok=True)

            # Existing portable files + user data
            with open(os.path.join(target_dir, "PackStation.exe"), "wb") as f:
                f.write(b"OLD_EXE_V155")
            with open(os.path.join(target_dir, "_internal", "core.pyd"), "wb") as f:
                f.write(b"OLD_CORE")
            with open(os.path.join(target_dir, "packstation.db"), "wb") as f:
                f.write(b"USER_SQLITE_DB_CONTENT")
            with open(os.path.join(target_dir, "packstation.db-wal"), "wb") as f:
                f.write(b"USER_WAL_DATA")
            with open(os.path.join(target_dir, "packstation-config.json"), "w", encoding="utf-8") as f:
                f.write('{"custom": "keep_me"}')
            vid_file = os.path.join(target_dir, "Videos", "2026-10-17", "ORDER1_Cam1.mp4")
            with open(vid_file, "wb") as f:
                f.write(b"REAL_VIDEO_EVIDENCE")

            # New staged portable files
            with open(os.path.join(staged_dir, "PackStation.exe"), "wb") as f:
                f.write(b"NEW_EXE_V156")
            with open(os.path.join(staged_dir, "_internal", "core.pyd"), "wb") as f:
                f.write(b"NEW_CORE")

            bat_path = create_and_run_updater_script(
                staged_dir, target_dir, launch_after=False, restart_app=False
            )
            proc = subprocess.run(["cmd.exe", "/c", bat_path], cwd=target_dir, timeout=20)
            self.assertEqual(proc.returncode, 0)

            # Verify binary updated while DB, WAL, config, Videos are untouched
            with open(os.path.join(target_dir, "PackStation.exe"), "rb") as f:
                self.assertEqual(f.read(), b"NEW_EXE_V156")
            with open(os.path.join(target_dir, "packstation.db"), "rb") as f:
                self.assertEqual(f.read(), b"USER_SQLITE_DB_CONTENT")
            with open(os.path.join(target_dir, "packstation.db-wal"), "rb") as f:
                self.assertEqual(f.read(), b"USER_WAL_DATA")
            with open(os.path.join(target_dir, "packstation-config.json"), "r", encoding="utf-8") as f:
                self.assertIn("keep_me", f.read())
            self.assertTrue(os.path.exists(vid_file))

            # Part B: Simulate mid-update copy failure (staged_dir missing at execution time) -> rollback must restore OLD binary and keep temp_update
            os.makedirs(os.path.join(staged_dir, "_internal"), exist_ok=True)
            with open(os.path.join(staged_dir, "PackStation.exe"), "wb") as f:
                f.write(b"BROKEN_STAGE_EXE")
            bat_path_fail = create_and_run_updater_script(
                staged_dir, target_dir, launch_after=False, restart_app=False
            )
            # Remove staged_dir before running batch script so robocopy fails with code >= 8 (code 16: source missing)
            shutil.rmtree(staged_dir)
            # Corrupt target PackStation.exe slightly after snapshot would not happen, or verify snapshot restores if copy fails
            proc_fail = subprocess.run(["cmd.exe", "/c", bat_path_fail], cwd=target_dir, timeout=20)
            self.assertEqual(proc_fail.returncode, 3)
            # Verify temp_update and rollback_snapshot were preserved and PackStation.exe is still intact (NEW_EXE_V156)
            self.assertTrue(os.path.exists(os.path.join(target_dir, "temp_update", "rollback_snapshot", "PackStation.exe")))
            with open(os.path.join(target_dir, "PackStation.exe"), "rb") as f:
                self.assertEqual(f.read(), b"NEW_EXE_V156")
            self.assertTrue(os.path.exists(os.path.join(target_dir, "logs", "updater_error.log")))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_cleanup_old_videos_preserves_sqlite_on_delete_failure_and_strict_prefix(self):
        """Test Requirement 4: Failed file deletion keeps both file and SQLite record with error logged; similar folder prefixes do not collide."""
        import tempfile
        from datetime import date, timedelta
        from unittest.mock import patch

        tmp_dir = tempfile.mkdtemp()
        try:
            db = Database(os.path.join(tmp_dir, "test.db"))
            db.initialize()
            rec = VideoRecorder(tmp_dir, db=db)

            # 1. Test prefix boundary: folder '2026-08-01' vs '2026-08-01_keep'
            dir_a = os.path.join(tmp_dir, "2026-08-01")
            dir_b = os.path.join(tmp_dir, "2026-08-01_keep")
            os.makedirs(dir_a, exist_ok=True)
            os.makedirs(dir_b, exist_ok=True)
            vid_a = os.path.join(dir_a, "ORD_A_Cam1.mp4")
            vid_b = os.path.join(dir_b, "ORD_B_Cam1.mp4")
            with open(vid_a, "wb") as f:
                f.write(b"a")
            with open(vid_b, "wb") as f:
                f.write(b"b")

            oid_a = db.start_order("ORD_A", 1)
            oid_b = db.start_order("ORD_B", 1)
            db.add_video(oid_a, "ORD_A_Cam1.mp4", vid_a, 1)
            db.add_video(oid_b, "ORD_B_Cam1.mp4", vid_b, 1)

            # Simulate failed deletion of dir_a (file still exists on disk)
            def _failing_rmtree(path, ignore_errors=False, onerror=None):
                if onerror:
                    try:
                        raise PermissionError("Simulated file lock: video is open in player")
                    except PermissionError:
                        import sys as _sys
                        onerror(os.remove, vid_a, _sys.exc_info())

            old_date = (date.today() - timedelta(days=45)).isoformat()
            locked_dir = os.path.join(tmp_dir, old_date)
            os.makedirs(locked_dir, exist_ok=True)
            locked_vid = os.path.join(locked_dir, "LOCKED_ORD_Cam1.mp4")
            with open(locked_vid, "wb") as f:
                f.write(b"locked_video_data")
            oid_locked = db.start_order("LOCKED_ORD", 1)
            db.add_video(oid_locked, "LOCKED_ORD_Cam1.mp4", locked_vid, 1)

            with patch("shutil.rmtree", side_effect=_failing_rmtree):
                with self.assertLogs("PackStation", level="ERROR") as cm:
                    rec.cleanup_old_videos(retention_days=30, db=db)
                self.assertTrue(any("Lỗi không thể xóa" in m for m in cm.output))

            # Both the locked physical file AND its SQLite record must still exist!
            self.assertTrue(os.path.exists(locked_vid))
            self.assertEqual(len(db.get_order_videos(oid_locked)), 1)

            # Now test remove_videos_in_folder directly when dir_a is deleted vs dir_b kept
            os.remove(vid_a)
            os.rmdir(dir_a)
            db.remove_videos_in_folder(dir_a)
            self.assertEqual(len(db.get_order_videos(oid_a)), 0)
            # dir_b ('2026-08-01_keep') must NOT be matched by '2026-08-01' prefix!
            self.assertEqual(len(db.get_order_videos(oid_b)), 1)

            rec.stop_all()
            db.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_cannot_delete_active_or_finishing_order_and_callback_ignores_deleted_order(self):
        """Test Requirement 5: Block deleting packing/finishing orders and prevent late recording callback from inserting into deleted order."""
        import tempfile
        tmp_dir = tempfile.mkdtemp()
        try:
            cfg = Config(tmp_dir)
            cfg.set("end_delay_seconds", 5.0)
            cfg.set("scan_cooldown_seconds", 0.0)
            db = Database(os.path.join(tmp_dir, "test.db"))
            db.initialize()
            mgr = OrderManager(db, cfg, video_recorder=None, audio_manager=None)

            # 1. Start order -> status is 'packing' -> delete_order must raise ValueError
            mgr.process_scan("ACTIVE_DEL_TEST", scanner_id=1)
            active = mgr.get_active_order(1)
            self.assertIsNotNone(active)
            order_id = active["id"]

            with self.assertRaises(ValueError):
                db.delete_order(order_id, active_order_ids=mgr.get_active_or_finishing_order_ids())

            # 2. Transition order to 'finishing' (delayed stop) -> delete_order must still raise ValueError
            mgr.process_scan("KETTHUC", scanner_id=1)
            self.assertTrue(mgr.is_finishing(1))
            with self.assertRaises(ValueError):
                db.delete_order(order_id, active_order_ids=mgr.get_active_or_finishing_order_ids())

            # 3. Cancel order -> status becomes 'cancelled' -> now deletion is allowed
            mgr.process_scan("HUYDON", scanner_id=1)
            db.delete_order(order_id, active_order_ids=mgr.get_active_or_finishing_order_ids())
            self.assertFalse(db.order_exists(order_id))

            # 4. Late video callback firing after order was deleted must NOT re-insert video or check rows
            vid_id = db.add_video(order_id, "GHOST.mp4", os.path.join(tmp_dir, "GHOST.mp4"), 1)
            chk_ok = db.set_video_check(order_id, 1, "ok", "Late callback")
            self.assertIsNone(vid_id)
            self.assertFalse(chk_ok)
            self.assertEqual(len(db.get_order_videos(order_id)), 0)
            self.assertEqual(len(db.get_video_checks(order_id)), 0)

            db.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_camera_password_dpapi_encryption_at_rest_and_legacy_migration(self):
        """Test Requirement 6: RTSP passwords are encrypted at rest in packstation-config.json via Windows DPAPI and legacy plaintext configs migrate cleanly."""
        import json
        import tempfile
        tmp_dir = tempfile.mkdtemp()
        try:
            # 1. Simulate legacy plaintext config on disk
            cfg_path = os.path.join(tmp_dir, "packstation-config.json")
            raw_rtsp = "rtsp://admin:CamSecretPass2026@192.168.1.108:554/cam/realmonitor?channel=1&subtype=0"
            legacy_data = {
                "stations": {
                    "1": {
                        "name": "Bàn 1",
                        "camera_source": raw_rtsp,
                        "cameras": [raw_rtsp],
                    }
                }
            }
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(legacy_data, f)

            # Load legacy config -> in-memory camera URL must be usable plaintext
            cfg = Config(tmp_dir)
            self.assertEqual(cfg.get_station_cameras(1)[0], raw_rtsp)

            # Migrate / save -> on-disk JSON must encrypt password and NEVER contain 'CamSecretPass2026'
            self.assertTrue(cfg.migrate_plaintext_credentials())
            with open(cfg_path, "r", encoding="utf-8") as f:
                disk_text = f.read()
            self.assertNotIn("CamSecretPass2026", disk_text)
            self.assertIn("ENC[dpapi:", disk_text)

            # Reload from encrypted config -> in-memory camera URL must decrypt back to original RTSP URL
            cfg2 = Config(tmp_dir)
            self.assertEqual(cfg2.get_station_cameras(1)[0], raw_rtsp)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 PACKSTATION UNIT TEST SUITE")
    print("=" * 60)
    unittest.main(verbosity=2)

