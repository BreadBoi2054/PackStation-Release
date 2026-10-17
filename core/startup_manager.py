"""Startup Manager - Windows auto-start via Registry."""
import os
import sys
import winreg
from core.logger import get_logger

log = get_logger()


REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "PackStation"


def get_exe_path() -> str:
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


def is_startup_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ)
        try:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return bool(value)
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except Exception:
        return False


def enable_startup() -> bool:
    try:
        exe_path = get_exe_path()
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
        winreg.CloseKey(key)
        log.info(f"[Startup] ✅ Enabled: {exe_path}")
        return True
    except Exception as e:
        log.error(f"[Startup] ❌ Enable error: {e}")
        return False


def disable_startup() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, APP_NAME)
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
        log.info("[Startup] ✅ Disabled")
        return True
    except Exception as e:
        log.error(f"[Startup] ❌ Disable error: {e}")
        return False


def set_startup(enabled: bool) -> bool:
    return enable_startup() if enabled else disable_startup()
