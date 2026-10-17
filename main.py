"""
PackStation - Phần mềm quản lý đóng gói hàng hóa + Camera
100% local, không cần internet, portable.
"""
import sys
import os
import signal


def get_base_dir():
    """Get the base directory - works for both dev and PyInstaller."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
sys.path.insert(0, BASE_DIR)


def main():
    import gc
    gc.set_threshold(50000, 10, 10)  # Tune GC for video frame workloads on weak CPUs

    # Initialize logger FIRST — before any other import
    from core.logger import get_logger, cleanup_old_logs
    log_dir = os.path.join(BASE_DIR, "logs")
    log = get_logger(log_dir)
    cleanup_old_logs(log_dir)

    from config import Config
    from database import Database
    from i18n import I18n

    config = Config(BASE_DIR)
    db = Database(config.db_path)
    db.initialize()

    # Crash recovery — clean up orders left in 'packing' from previous crash
    recovered = db.recover_crashed_orders()
    if recovered:
        log.warning(f"[CrashRecovery] Recovered {recovered} order(s) left from previous crash")

    i18n = I18n(config.language, os.path.join(BASE_DIR, "i18n"))

    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    from ui.app_window import AppWindow
    app = AppWindow(config, db, i18n)

    def on_closing():
        log.info("[App] Shutting down...")
        app.cleanup()
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_closing)
    signal.signal(signal.SIGINT, lambda s, f: on_closing())

    app.mainloop()

if __name__ == "__main__":
    main()
