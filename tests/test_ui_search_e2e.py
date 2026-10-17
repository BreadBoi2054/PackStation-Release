"""End-to-End UI & Database test verifying scan history and orders search integration."""
import os
import sys
import tempfile
import time
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database
from config import Config
from i18n import I18n
from ui.app_window import AppWindow


class TestUISearchE2E(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.config = Config(self.tmp_dir)
        self.config.set("sound_enabled", False)
        self.config.set("auto_record", False)
        self.config.set("stations", {
            "1": {
                "name": "Bàn 1",
                "camera_source": "",
                "camera_type": "rtsp",
            }
        })
        self.db = Database(self.config.db_path)
        self.db.initialize()
        self.i18n = I18n(self.config.i18n_dir, self.config.language)

        # Initialize App
        self.app = AppWindow(self.config, self.db, self.i18n)
        self.app.withdraw()  # Run headless without opening window on screen
        self.app.order_mgr.scan_cooldown_seconds = 0
        self.app.order_mgr.end_delay_seconds = 0

    def tearDown(self):
        try:
            self.app.cleanup()
            self.app.destroy()
        except Exception:
            pass
        self.db.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_scan_flows_to_history_and_orders_search(self):
        # 1. Start on camera page
        self.app._navigate("camera")
        self.app.update()

        # 2. Simulate barcode scanner inputting order code
        test_sn = "SHOPEE_VN_SEARCH_TEST_777"
        self.app._scan_entry.delete(0, "end")
        self.app._scan_entry.insert(0, test_sn)
        self.app._on_manual_scan()

        # Allow background thread and Tkinter event loop to process
        t0 = time.time()
        while time.time() - t0 < 5.0:
            if hasattr(self.app, "_process_ui_queue"):
                self.app._process_ui_queue()
            self.app.update()
            log_content = self.app._log_text.get("0.0", "end")
            if test_sn in log_content and "Bắt đầu" in log_content:
                break
            time.sleep(0.05)
        self.app.update()

        # 3. Verify Camera Page "Lịch sử quét hôm nay" received the log
        log_content = self.app._log_text.get("0.0", "end")
        self.assertIn(test_sn, log_content, "Order should appear in camera page scan history")
        self.assertIn("Bắt đầu", log_content)

        # 4. Navigate to "Đơn hàng" (Orders page)
        self.app._navigate("orders")
        self.app.update()

        # Verify order exists in the orders table
        self.assertIsNotNone(self.app._orders_list_frame)
        rendered_texts = []
        for child in self.app._orders_list_frame.winfo_children():
            for sub in child.winfo_children():
                if hasattr(sub, "cget"):
                    try:
                        rendered_texts.append(sub.cget("text"))
                    except Exception:
                        pass

        self.assertTrue(any(test_sn in t for t in rendered_texts),
                        f"Order {test_sn} must appear in rendered orders table! Rendered: {rendered_texts}")

        # 5. Test Search Bar with matching keyword
        self.app._order_search_entry.delete(0, "end")
        self.app._order_search_entry.insert(0, "777")
        self.app._refresh_orders_list()
        self.app.update()

        search_texts = []
        for child in self.app._orders_list_frame.winfo_children():
            for sub in child.winfo_children():
                if hasattr(sub, "cget"):
                    try:
                        search_texts.append(sub.cget("text"))
                    except Exception:
                        pass
        self.assertTrue(any(test_sn in t for t in search_texts), "Search by '777' must find order!")

        # 6. Test Search Bar with non-matching keyword
        self.app._order_search_entry.delete(0, "end")
        self.app._order_search_entry.insert(0, "KHONG_CO_DON_NAY")
        self.app._refresh_orders_list()
        self.app.update()

        not_found_texts = []
        for child in self.app._orders_list_frame.winfo_children():
            if hasattr(child, "cget"):
                try:
                    not_found_texts.append(child.cget("text"))
                except Exception:
                    pass
        self.assertTrue(any("Không tìm thấy đơn hàng nào" in t for t in not_found_texts),
                        "Should display not found notice when query doesn't match")

        # 7. Clear search restores full list
        self.app._clear_orders_search()
        self.app.update()
        self.assertEqual(self.app._order_search_entry.get(), "")

        # 8. Scan STOP code and verify order transitions to completed
        self.app.order_mgr.process_scan("STOP")
        self.app.update()
        time.sleep(0.05)
        self.app.update()

        db_order = self.db.conn.execute("SELECT * FROM orders WHERE order_sn=?", (test_sn,)).fetchone()
        self.assertEqual(db_order["status"], "completed")


if __name__ == "__main__":
    unittest.main()
