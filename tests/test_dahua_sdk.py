"""Unit test for DahuaNetSDK module."""
import os
import sys
import unittest

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.dahua_sdk import DahuaNetSDK, NETSDK_ERRORS


class TestDahuaNetSDK(unittest.TestCase):
    """Test suite for Dahua NetSDK wrapper."""

    def setUp(self):
        self.sdk = DahuaNetSDK()

    def test_sdk_loaded(self):
        """Test that 64-bit DLLs are loaded properly."""
        self.assertTrue(self.sdk.is_available, "Dahua NetSDK 64-bit DLL should be loaded")

    def test_sdk_init_cleanup(self):
        """Test CLIENT_Init and CLIENT_Cleanup cycle."""
        ok = self.sdk.init()
        self.assertTrue(ok, "CLIENT_Init should return True")
        self.sdk.cleanup()
        self.assertFalse(self.sdk._init_handle)

    def test_error_translations(self):
        """Test error code mapping to human-readable strings."""
        self.assertIn("Sai mật khẩu", self.sdk.get_last_error_message(1))
        self.assertIn("Quá thời gian", self.sdk.get_last_error_message(3))
        self.assertIn("Lỗi mạng", self.sdk.get_last_error_message(14))

    def test_login_failure_handling(self):
        """Test login failure on non-existent IP returns 0 and error message."""
        # Non-routable IP to test timeout or network failure handling
        login_id, msg = self.sdk.login("192.0.2.1", "wrong_pwd", port=37777)
        self.assertEqual(login_id, 0)
        self.assertTrue(len(msg) > 0)
        self.sdk.cleanup()


if __name__ == "__main__":
    unittest.main()
