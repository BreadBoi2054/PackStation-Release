"""Test end-to-end flow from barcode scan to Orders page search."""
import os
import sys
import tempfile
import unittest
import time
from datetime import date

# Ensure repo root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database
from config import Config
from core.order_manager import OrderManager


class TestScanToOrdersSearchFlow(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmp_dir, "test.db"))
        self.db.initialize()
        self.config = Config(self.tmp_dir)
        self.om = OrderManager(self.db, self.config)
        self.om.scan_cooldown_seconds = 0
        self.om.end_delay_seconds = 0
        self.log_messages = []
        self.om.on_log = lambda msg, sid: self.log_messages.append(msg)

    def tearDown(self):
        self.db.close()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_scanned_order_appears_in_database_and_search(self):
        # 1. Simulate scanning Shopee order
        shopee_code = "SPX_VN_260927_8899A"
        self.om.process_scan(shopee_code, scanner_id=1)

        # Verify active order
        active = self.om.get_active_order(1)
        self.assertIsNotNone(active, "Active order should be set")
        self.assertEqual(active["order_sn"], shopee_code)

        # 2. Check today's orders list (used by Orders page default view)
        today_orders = self.db.get_today_orders()
        self.assertEqual(len(today_orders), 1, "Today's orders should have exactly 1 order")
        self.assertEqual(today_orders[0]["order_sn"], shopee_code)
        self.assertEqual(today_orders[0]["status"], "packing")

        # 3. Test search by full tracking code
        results_full = self.db.search_orders(shopee_code)
        self.assertEqual(len(results_full), 1)
        self.assertEqual(results_full[0]["order_sn"], shopee_code)

        # 4. Test search by partial tracking code (e.g. '8899A' or 'SPX')
        results_partial_suffix = self.db.search_orders("8899A")
        self.assertEqual(len(results_partial_suffix), 1, "Should find by partial suffix '8899A'")
        self.assertEqual(results_partial_suffix[0]["order_sn"], shopee_code)

        results_partial_prefix = self.db.search_orders("SPX")
        self.assertEqual(len(results_partial_prefix), 1, "Should find by partial prefix 'SPX'")

        # 5. Test search by date (e.g. today's date YYYY-MM-DD)
        today_str = date.today().isoformat()
        results_date = self.db.search_orders(today_str)
        self.assertGreaterEqual(len(results_date), 1, "Should find by date query")

        # 6. Test finishing order with STOP code
        self.om.process_scan("STOP", scanner_id=1)
        self.assertIsNone(self.om.get_active_order(1))

        # Check search after completion
        results_completed = self.db.search_orders("8899A")
        self.assertEqual(len(results_completed), 1)
        self.assertEqual(results_completed[0]["status"], "completed")
        self.assertIsNotNone(results_completed[0]["end_time"])

    def test_multiple_scanned_orders_filtered_by_search(self):
        codes = [
            "VN_SHOPEE_101",
            "VN_TIKTOK_202",
            "VN_LAZADA_303",
        ]
        for c in codes:
            self.om.process_scan(c, scanner_id=1)
            self.om.process_scan("STOP", scanner_id=1)

        all_orders = self.db.get_today_orders()
        self.assertEqual(len(all_orders), 3)

        # Search TIKTOK -> only 1 match
        tiktok_res = self.db.search_orders("TIKTOK")
        self.assertEqual(len(tiktok_res), 1)
        self.assertEqual(tiktok_res[0]["order_sn"], "VN_TIKTOK_202")

        # Search 101 -> only 1 match
        res_101 = self.db.search_orders("101")
        self.assertEqual(len(res_101), 1)
        self.assertEqual(res_101[0]["order_sn"], "VN_SHOPEE_101")

        # Search 'VN' -> all 3 match
        vn_res = self.db.search_orders("VN")
        self.assertEqual(len(vn_res), 3)

        # Search nonexistent
        empty_res = self.db.search_orders("NON_EXISTENT_CODE")
        self.assertEqual(len(empty_res), 0)


if __name__ == "__main__":
    unittest.main()
