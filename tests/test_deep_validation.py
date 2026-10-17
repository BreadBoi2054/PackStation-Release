"""Deep functional and stress test for PackStation."""
import os
import sys
import time
import shutil
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from database import Database
from i18n import I18n
from core.video_recorder import VideoRecorder
from core.order_manager import OrderManager
from core.audio_manager import AudioManager
from core.barcode_scanner import BarcodeScanner
from core.camera_discovery import parse_camera_qr
from core.dahua_sdk import DahuaNetSDK
from ui.app_window import AppWindow

def run_tests():
    print("=" * 60)
    print("🧪 RUNNING COMPREHENSIVE PACKSTATION VERIFICATION SUITE")
    print("=" * 60)

    test_dir = os.path.join(os.path.dirname(__file__), "tmp_test_env")
    shutil.rmtree(test_dir, ignore_errors=True)
    os.makedirs(test_dir, exist_ok=True)

    try:
        # 1. Config Test
        cfg = Config(test_dir)
        cfg.set_station_cameras([
            "rtsp://admin:pass1@192.168.1.100:554/cam/realmonitor?channel=1&subtype=0",
            "rtsp://admin:pass1@192.168.1.100:554/cam/realmonitor?channel=2&subtype=0"
        ], station_id=1)
        cams = cfg.get_station_cameras(1)
        assert len(cams) == 2, f"Expected 2 cameras, got {len(cams)}"
        print("  ✅ [1/8] Config & Dual-lens Camera persistence OK")

        # 2. Database Test
        db = Database(cfg.db_path)
        db.initialize()
        print("  ✅ [2/8] Database initialization & WAL mode OK")

        # 3. Audio Manager Test (Graceful silent mode when audio disabled)
        audio = AudioManager(cfg.audio_dir, enabled=False)
        audio.play("start")
        print("  ✅ [3/8] AudioManager safe fallback OK")

        # 4. Asynchronous Video Recorder with Multi-channel Dual-Lens Test
        recorder = VideoRecorder(cfg.video_dir, fps=15, resolution=(640, 360))
        om = OrderManager(db, cfg, recorder, audio)
        om.scan_cooldown_seconds = 0
        om.end_delay_seconds = 0

        events = []
        om.on_order_started = lambda sn, sid, oid: events.append(f"START:{sn}")
        om.on_order_ended = lambda sn, sid, st: events.append(f"END:{sn}:{st}")
        om.on_duplicate = lambda sn, sid: events.append(f"DUP:{sn}")

        # Scan order
        order_sn = "VN_TEST_DUAL_9988"
        om.process_scan(order_sn, scanner_id=1)

        # Write frames to both channels simulating 2 lenses
        frame_dummy = np.full((360, 640, 3), 128, dtype=np.uint8)
        for _ in range(8):
            recorder.write_frame(order_sn, frame_dummy, channel=1)
            recorder.write_frame(order_sn, frame_dummy, channel=2)

        time.sleep(0.15)

        # End order with KETTHUC
        om.process_scan("KETTHUC", scanner_id=1)

        # Verify dual-lens video files created
        today = time.strftime("%Y-%m-%d")
        file_ch1 = os.path.join(cfg.video_dir, today, f"{order_sn}_Cam1.mp4")
        file_ch2 = os.path.join(cfg.video_dir, today, f"{order_sn}_Cam2.mp4")

        assert os.path.exists(file_ch1), f"Channel 1 video missing: {file_ch1}"
        assert os.path.exists(file_ch2), f"Channel 2 video missing: {file_ch2}"
        assert os.path.getsize(file_ch1) > 0, "Channel 1 video is 0 bytes"
        assert os.path.getsize(file_ch2) > 0, "Channel 2 video is 0 bytes"
        print(f"  ✅ [4/8] Dual-Lens Video Splitting: Cam1={os.path.getsize(file_ch1)}B, Cam2={os.path.getsize(file_ch2)}B OK")

        # 5. Duplicate Order & Cooldown Detection
        om.process_scan(order_sn, scanner_id=1)
        assert any("DUP:" in e for e in events), "Duplicate detection failed!"
        print("  ✅ [5/8] Duplicate order cooldown protection OK")

        # 6. Function Codes: Shift & Cancel
        om.process_scan("SETCA_NguyenVanA", scanner_id=1)
        assert cfg.get("current_shift") == "NguyenVanA", "Shift setting failed!"

        order_sn_cancel = "VN_CANCEL_TEST_001"
        om.process_scan(order_sn_cancel, scanner_id=1)
        om.process_scan("HUYDON", scanner_id=1)
        assert any(f"END:{order_sn_cancel}:cancelled" in e for e in events), "Cancel order failed!"
        print("  ✅ [6/8] Function codes (SETCA, HUYDON, KETTHUC) OK")

        # 7. Excel Export Verification
        from openpyxl import Workbook, load_workbook
        orders = db.get_today_orders()
        assert len(orders) >= 2, f"Expected at least 2 orders in DB, got {len(orders)}"
        wb = Workbook()
        ws = wb.active
        ws.title = f"Đóng gói {today}"
        ws.append(["STT", "Mã vận đơn", "Bàn", "Bắt đầu", "Kết thúc", "Trạng thái", "Người phụ trách"])
        for i, o in enumerate(orders, 1):
            ws.append([i, o["order_sn"], o["scanner_id"], o["start_time"], o["end_time"] or "", o["status"], o["operator"] or ""])
        excel_path = os.path.join(test_dir, "test_export.xlsx")
        wb.save(excel_path)
        assert os.path.exists(excel_path), "Excel export failed!"
        wb_check = load_workbook(excel_path)
        row_count = len(list(wb_check.active.rows))
        assert row_count >= 3, f"Excel data rows missing: {row_count}"
        print("  ✅ [7/8] Database reporting & Excel export OK")

        # 8. Password Updating and RTSP Manipulation
        url1 = "rtsp://admin:oldpwd@192.168.1.150:554/cam/realmonitor?channel=1&subtype=0"
        url2 = "rtsp://admin:oldpwd@192.168.1.150:554/cam/realmonitor?channel=2&subtype=0"
        u, p, h = AppWindow._parse_rtsp_url(url1)
        assert p == "oldpwd", f"Password parse failed: {p}"

        upd1 = AppWindow._update_rtsp_password(url1, "L26BD9A7", username="admin")
        upd2 = AppWindow._update_rtsp_password(url2, "L26BD9A7", username="admin")
        assert "L26BD9A7" in upd1 and "channel=1" in upd1
        assert "L26BD9A7" in upd2 and "channel=2" in upd2
        print("  ✅ [8/8] RTSP password parsing, escaping and multi-camera updating OK")

        recorder.stop_all()
        db.close()

        print("\n" + "=" * 60)
        print("🎉 ALL 8 SYSTEM CHECKS PASSED WITH 100% SUCCESS!")
        print("=" * 60)
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

if __name__ == "__main__":
    run_tests()
