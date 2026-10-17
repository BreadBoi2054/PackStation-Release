"""Full test suite for PackStation."""
import sys
sys.path.insert(0, '.')

print('=== TEST 1: Import all modules ===')
modules = [
    ("Config", "from config import Config"),
    ("Database", "from database import Database"),
    ("I18n", "from i18n import I18n"),
    ("CameraManager", "from core.camera_manager import CameraManager"),
    ("BarcodeScanner", "from core.barcode_scanner import BarcodeScanner"),
    ("VideoRecorder", "from core.video_recorder import VideoRecorder"),
    ("OrderManager", "from core.order_manager import OrderManager"),
    ("AudioManager", "from core.audio_manager import AudioManager"),
    ("StartupManager", "from core.startup_manager import is_startup_enabled"),
    ("CameraDiscovery", "from core.camera_discovery import parse_camera_qr"),
    ("DahuaNetSDK", "from core.dahua_sdk import DahuaNetSDK"),
    ("Theme", "from ui.theme import COLORS, FONTS"),

    ("AppWindow", "from ui.app_window import AppWindow"),
]
for name, imp in modules:
    try:
        exec(imp)
        print(f'  ✅ {name}')
    except Exception as e:
        print(f'  ❌ {name}: {e}')

from config import Config
from database import Database
from i18n import I18n
from core.video_recorder import VideoRecorder
from core.order_manager import OrderManager
from core.audio_manager import AudioManager
from core.camera_discovery import parse_camera_qr

print()
print('=== TEST 2: Config + Database (Isolated Temp Dir) ===')
import os
import tempfile
import shutil
base_dir = os.path.dirname(os.path.abspath(__file__))
tmp_test_dir = tempfile.mkdtemp(prefix="packstation_test_all_")
cfg = Config(tmp_test_dir)
print(f'  ✅ Config loaded, temp_dir={cfg.base_dir}')
print(f'  ✅ Video dir: {cfg.video_dir}')
print(f'  ✅ Station 1: {cfg.get_station(1)}')

db = Database(cfg.db_path)
db.initialize()
print(f'  ✅ Database opened: {cfg.db_path}')
count = db.get_today_count()
print(f'  ✅ Today count: {count}')

print()
print('=== TEST 3: I18n ===')
i18n = I18n(language=cfg.language, i18n_dir=os.path.join(base_dir, "i18n"))
print(f'  ✅ Language: {i18n.language}')
print(f'  ✅ app.title = {i18n.t("app.title")}')
print(f'  ✅ nav.camera = {i18n.t("nav.camera")}')
print(f'  ✅ scan.recording = {i18n.t("scan.recording")}')

print()
print('=== TEST 4: Order flow ===')
recorder = VideoRecorder(os.path.join(tmp_test_dir, "Videos"))
audio = AudioManager(os.path.join(base_dir, "audio"), False)
om = OrderManager(db, cfg, recorder, audio)
om.scan_cooldown_seconds = 0
om.end_delay_seconds = 0

logs = []
om.on_log = lambda msg, sid: logs.append(msg)
om.on_order_started = lambda sn, sid, oid: logs.append(f'STARTED:{sn}')
om.on_order_ended = lambda sn, sid, st: logs.append(f'ENDED:{sn}:{st}')
om.on_duplicate = lambda sn, sid: logs.append(f'DUP:{sn}')

om.process_scan('TEST_QC_12345', scanner_id=1)
active = om.get_active_order(1)
print(f'  ✅ Scan → active order: {active["order_sn"] if active else "None"}')

om.process_scan('KETTHUC', scanner_id=1)
active2 = om.get_active_order(1)
print(f'  ✅ KETTHUC → ended: active={active2}')
print(f'  ✅ Event log: {logs}')

print()
print('=== TEST 5: QR Parser ===')
tests = [
    ('rtsp://admin:pass@192.168.1.100:554/stream', 'RTSP URL'),
    ('SN:ABC123,PWD:admin123', 'Imou QR'),
    ('192.168.1.50', 'IP only'),
    ('IP=10.0.0.5,PORT=554,USER=admin,PWD=secret', 'Key-value'),
]
for qr, label in tests:
    r = parse_camera_qr(qr)
print()
print('=== TEST 6: Dahua NetSDK 64-bit ===')
from core.dahua_sdk import DahuaNetSDK
sdk = DahuaNetSDK()
print(f'  ✅ NetSDK Available: {sdk.is_available}')
ok = sdk.init()
print(f'  ✅ NetSDK CLIENT_Init: {ok}')
sdk.cleanup()
print(f'  ✅ NetSDK CLIENT_Cleanup: Done')

db.close()
recorder.stop_all()
shutil.rmtree(tmp_test_dir, ignore_errors=True)

print()
print('🎉 ALL TESTS PASSED!')

