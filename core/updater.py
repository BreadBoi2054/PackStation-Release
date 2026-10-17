"""Auto-updater module for PackStation.

Implements safe update checking, staging, verification, SQLite online backup, and rollback:
1. Online SQLite Backup API (`sqlite3.Connection.backup`) to capture WAL state consistently,
   followed by `PRAGMA integrity_check` and table readability verification before updating.
2. Strict separation between Portable mode (requires valid portable Release ZIP containing
   `PackStation.exe` + required runtime folders, verifies source URL, size, and SHA-256 digest;
   never falls back to source `zipball_url`) and Source Git mode (`git pull --ff-only`).
3. Safe batch updater (`updater_apply.bat`) that verifies old process exit, creates a rollback
   snapshot before copying, checks `robocopy` exit codes (`< 8`), restores from snapshot on
   failure while keeping staging logs, and preserves `packstation.db*`, `packstation-config.json`,
   `Videos/`, and `logs/`.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Callable, Optional

from core.logger import get_logger

log = get_logger()

CURRENT_VERSION = "v1.5.5"
GITHUB_REPO = "BreadBoi2054/PackStation-Release"

# Never overwrite these files/folders during an update
PROTECTED_NAMES = {
    "packstation.db",
    "packstation.db-wal",
    "packstation.db-shm",
    "packstation-config.json",
    "videos",
    "logs",
    "temp_update",
    ".git",
}

TRUSTED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "api.github.com",
    "release-assets.githubusercontent.com",
    "codeload.github.com",
    "127.0.0.1",
    "localhost",
}

REQUIRED_PORTABLE_ITEMS = ("PackStation.exe",)
REQUIRED_PORTABLE_DIRS_ANY = ("_internal", "i18n", "assets", "libs")


def parse_version(version_str: str) -> tuple:
    """Parse version string like 'v1.5.5' or '1.5.5.0' into integer tuple (1, 5, 5)."""
    if not version_str:
        return (0, 0, 0)
    cleaned = version_str.strip().lstrip("vV")
    nums = [int(x) for x in re.findall(r"\d+", cleaned)]
    while len(nums) > 3 and nums[-1] == 0:
        nums.pop()
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def is_newer_version(latest_tag: str, current_version: str = CURRENT_VERSION) -> bool:
    """Return True if latest_tag is strictly newer than current_version."""
    return parse_version(latest_tag) > parse_version(current_version)


def get_update_mode(target_dir: str) -> str:
    """Determine whether target_dir should update in 'portable' mode or 'source_git' mode."""
    if getattr(sys, "frozen", False):
        return "portable"
    exe_path = os.path.join(target_dir, "PackStation.exe")
    if os.path.isfile(exe_path):
        return "portable"
    git_dir = os.path.join(target_dir, ".git")
    if os.path.isdir(git_dir):
        return "source_git"
    return "portable"


def is_trusted_download_url(url: str) -> bool:
    """Verify download URL is from a trusted GitHub release host (or local file:// for isolated tests) and not a source zipball."""
    if not url:
        return False
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme == "file":
        return True
    if parsed.scheme not in ("https", "http"):
        return False
    host = (parsed.hostname or "").lower()
    if host not in TRUSTED_DOWNLOAD_HOSTS:
        return False
    # Reject GitHub auto-generated source code zipball/tarball URLs
    if "/zipball/" in parsed.path.lower() or "/tarball/" in parsed.path.lower():
        return False
    return True


def _extract_sha256_from_asset_or_body(asset: dict, body: str, asset_name: str) -> str:
    """Extract expected SHA-256 hex digest from GitHub asset metadata or release notes if available."""
    digest = str(asset.get("digest") or "").strip()
    if digest.lower().startswith("sha256:"):
        candidate = digest.split(":", 1)[1].strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", candidate):
            return candidate
    if body:
        # Match patterns like: SHA256: <64-hex> or <64-hex>  PackStation-v1.5.5-Windows.zip
        for m in re.finditer(r"\b([0-9a-fA-F]{64})\b", body):
            return m.group(1).lower()
    return ""


def check_for_update(
    repo: str = GITHUB_REPO,
    current_version: str = CURRENT_VERSION,
    target_dir: Optional[str] = None,
    timeout: int = 10,
) -> dict:
    """Check GitHub Releases API for a newer version of PackStation.

    Never falls back to source `zipball_url` for portable updates.
    """
    mode = get_update_mode(target_dir) if target_dir else ("portable" if getattr(sys, "frozen", False) else "source_git")
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PackStation-Updater",
    }
    result = {
        "has_update": False,
        "has_valid_asset": False,
        "mode": mode,
        "current_version": current_version,
        "latest_version": current_version,
        "release_name": "",
        "release_notes": "",
        "html_url": f"https://github.com/{repo}/releases",
        "download_url": "",
        "asset_name": "",
        "asset_size": 0,
        "asset_sha256": "",
        "error": None,
    }

    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tag_name = data.get("tag_name", "").strip()
        if not tag_name:
            result["error"] = "Không tìm thấy thông tin tag phiên bản trên GitHub."
            return result

        result["latest_version"] = tag_name
        result["release_name"] = data.get("name") or tag_name
        result["release_notes"] = data.get("body") or ""
        result["html_url"] = data.get("html_url") or result["html_url"]
        result["has_update"] = is_newer_version(tag_name, current_version)

        # Find portable Windows ZIP asset (strictly from release assets, NEVER zipball_url)
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            dl_url = asset.get("browser_download_url", "")
            if (
                name.lower().endswith(".zip")
                and "packstation" in name.lower()
                and is_trusted_download_url(dl_url)
            ):
                result["download_url"] = dl_url
                result["asset_name"] = name
                result["asset_size"] = int(asset.get("size", 0))
                result["asset_sha256"] = _extract_sha256_from_asset_or_body(
                    asset, result["release_notes"], name
                )
                result["has_valid_asset"] = True
                break

        if result["has_update"] and mode == "portable" and not result["has_valid_asset"]:
            result["error"] = (
                f"Phiên bản {tag_name} trên GitHub không có gói cài đặt portable (.zip) hợp lệ. "
                "Đã giữ nguyên phiên bản đang chạy."
            )

        return result

    except urllib.error.HTTPError as e:
        if e.code == 404:
            result["error"] = "Chưa có bản Release nào trên kho GitHub."
        else:
            result["error"] = f"Lỗi máy chủ GitHub (HTTP {e.code})."
        return result
    except urllib.error.URLError as e:
        result["error"] = f"Không thể kết nối tới GitHub: {e.reason}"
        return result
    except Exception as e:
        result["error"] = f"Lỗi khi kiểm tra cập nhật: {e}"
        return result


def backup_sqlite_database(db_path: str, backup_path: str) -> dict:
    """Create a consistent online backup of SQLite database (including uncheckpointed WAL data)
    using SQLite Backup API, then verify integrity and table readability.

    Returns: {"ok": bool, "backup_path": str, "error": str|None}
    """
    if not os.path.exists(db_path):
        return {"ok": True, "backup_path": "", "error": None}

    src_conn = None
    dst_conn = None
    verify_conn = None
    try:
        src_conn = sqlite3.connect(db_path, timeout=10.0)
        dst_conn = sqlite3.connect(backup_path, timeout=10.0)
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        dst_conn = None

        # Verify integrity and readability of the backup database
        verify_conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True, timeout=5.0)
        integrity_row = verify_conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity_row or str(integrity_row[0]).strip().lower() != "ok":
            raise RuntimeError(f"PRAGMA integrity_check thất bại: {integrity_row}")

        # Verify tables can be queried and compare orders count if orders table exists
        src_tables = {
            r[0]
            for r in src_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        bak_tables = {
            r[0]
            for r in verify_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if not src_tables.issubset(bak_tables):
            raise RuntimeError("Bản sao lưu thiếu bảng dữ liệu so với database gốc.")

        if "orders" in src_tables:
            src_count = src_conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            bak_count = verify_conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            if bak_count < src_count:
                raise RuntimeError(
                    f"Bản sao lưu thiếu dữ liệu đơn hàng ({bak_count} < {src_count})."
                )

        verify_conn.close()
        verify_conn = None
        src_conn.close()
        src_conn = None
        return {"ok": True, "backup_path": backup_path, "error": None}

    except Exception as e:
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception:
                pass
        return {"ok": False, "backup_path": "", "error": f"Sao lưu SQLite thất bại: {e}"}
    finally:
        for conn in (verify_conn, dst_conn, src_conn):
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


def backup_user_data(target_dir: str) -> dict:
    """Create verified safety backups of packstation.db (via SQLite Backup API) and packstation-config.json.

    Returns: {"ok": bool, "backups": list[str], "error": str|None}
    """
    backed_up = []
    ts = int(time.time())

    # 1. Online SQLite Backup (captures WAL accurately)
    db_src = os.path.join(target_dir, "packstation.db")
    if os.path.exists(db_src):
        db_dst = os.path.join(target_dir, f"packstation.db.backup_{ts}")
        res = backup_sqlite_database(db_src, db_dst)
        if not res["ok"]:
            log.error(f"[Updater] ❌ {res['error']}")
            return {"ok": False, "backups": [], "error": res["error"]}
        if res["backup_path"]:
            backed_up.append(res["backup_path"])
            log.info(f"[Updater] 🛡️ Đã sao lưu & kiểm tra toàn vẹn SQLite: {res['backup_path']}")

    # 2. Config JSON Backup
    cfg_src = os.path.join(target_dir, "packstation-config.json")
    if os.path.exists(cfg_src):
        cfg_dst = os.path.join(target_dir, f"packstation-config.json.backup_{ts}")
        try:
            shutil.copy2(cfg_src, cfg_dst)
            if not os.path.exists(cfg_dst) or os.path.getsize(cfg_dst) != os.path.getsize(cfg_src):
                raise RuntimeError("Kích thước file sao lưu cấu hình không khớp.")
            backed_up.append(cfg_dst)
            log.info(f"[Updater] 🛡️ Đã sao lưu cấu hình trước cập nhật: {cfg_dst}")
        except Exception as e:
            err_msg = f"Không thể sao lưu file cấu hình packstation-config.json: {e}"
            log.error(f"[Updater] ❌ {err_msg}")
            return {"ok": False, "backups": backed_up, "error": err_msg}

    return {"ok": True, "backups": backed_up, "error": None}


def strip_protected_items(staged_dir: str):
    """Remove any user data or config files from the extracted update folder so they never overwrite local data."""
    if not os.path.isdir(staged_dir):
        return
    for item in os.listdir(staged_dir):
        item_lower = item.lower()
        if item_lower in PROTECTED_NAMES or item_lower.startswith("packstation.db"):
            full_path = os.path.join(staged_dir, item)
            try:
                if os.path.isdir(full_path):
                    shutil.rmtree(full_path, ignore_errors=True)
                else:
                    os.remove(full_path)
            except Exception:
                pass


def validate_portable_package(staged_dir: str) -> tuple[bool, str]:
    """Verify that the extracted update directory is a valid PackStation portable build
    containing PackStation.exe and required runtime folders (rejects source-only archives).
    """
    if not staged_dir or not os.path.isdir(staged_dir):
        return False, "Thư mục giải nén gói cập nhật không tồn tại."

    for req_file in REQUIRED_PORTABLE_ITEMS:
        fpath = os.path.join(staged_dir, req_file)
        if not os.path.isfile(fpath) or os.path.getsize(fpath) <= 0:
            return (
                False,
                f"Gói cập nhật không hợp lệ: Thiếu file thực thi '{req_file}' "
                "(gói chỉ chứa mã nguồn hoặc bị hỏng, không phải bản portable Windows).",
            )

    has_runtime_dir = any(
        os.path.isdir(os.path.join(staged_dir, d)) for d in REQUIRED_PORTABLE_DIRS_ANY
    )
    if not has_runtime_dir:
        return (
            False,
            "Gói cập nhật thiếu các thư mục thành phần bắt buộc (_internal/i18n/assets/libs).",
        )

    return True, ""


def download_and_stage_update(
    download_url: str,
    target_dir: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    expected_size: int = 0,
    expected_sha256: str = "",
    timeout: int = 60,
) -> dict:
    """Download the release ZIP, verify size & SHA-256, validate portable contents,
    perform verified SQLite online backup, and strip protected files.

    Returns dict: {"ok": bool, "staged_dir": str, "backups": list, "error": str|None}
    """
    if not is_trusted_download_url(download_url):
        return {
            "ok": False,
            "staged_dir": "",
            "backups": [],
            "error": "Nguồn tải gói cập nhật không hợp lệ hoặc là gói mã nguồn (zipball).",
        }

    # Step 1: Perform and verify SQLite + Config backup BEFORE downloading/applying
    if progress_callback:
        progress_callback(2, 100, "Đang sao lưu và kiểm tra toàn vẹn cơ sở dữ liệu SQLite...")

    backup_res = backup_user_data(target_dir)
    if not backup_res["ok"]:
        return {
            "ok": False,
            "staged_dir": "",
            "backups": [],
            "error": backup_res["error"],
        }

    temp_root = os.path.join(target_dir, "temp_update")
    zip_path = os.path.join(temp_root, "update_package.zip")
    extract_dir = os.path.join(temp_root, "extracted")

    try:
        if os.path.exists(temp_root):
            shutil.rmtree(temp_root, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)

        if progress_callback:
            progress_callback(5, 100, "Đang kết nối tải bản cập nhật...")

        hasher = hashlib.sha256()
        headers = {"User-Agent": "PackStation-Updater"}
        req = urllib.request.Request(download_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_len = int(resp.headers.get("Content-Length", 0))
            total_size = expected_size if expected_size > 0 else content_len
            downloaded = 0
            chunk_size = 256 * 1024  # 256 KB

            with open(zip_path, "wb") as out_file:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        mb_done = downloaded / (1024 * 1024)
                        if total_size > 0:
                            mb_total = total_size / (1024 * 1024)
                            pct = min(88, max(5, int(downloaded * 88 / total_size)))
                            progress_callback(
                                pct, 100, f"Đang tải: {mb_done:.1f} / {mb_total:.1f} MB ({pct}%)"
                            )
                        else:
                            progress_callback(50, 100, f"Đang tải: {mb_done:.1f} MB...")

        if expected_size > 0 and downloaded != expected_size:
            shutil.rmtree(temp_root, ignore_errors=True)
            return {
                "ok": False,
                "staged_dir": "",
                "backups": backup_res["backups"],
                "error": f"Kích thước gói tải về không khớp ({downloaded} != {expected_size} bytes).",
            }

        if expected_sha256:
            actual_sha256 = hasher.hexdigest().lower()
            if actual_sha256 != expected_sha256.strip().lower():
                shutil.rmtree(temp_root, ignore_errors=True)
                return {
                    "ok": False,
                    "staged_dir": "",
                    "backups": backup_res["backups"],
                    "error": "Mã kiểm tra toàn vẹn SHA-256 của gói cập nhật không khớp!",
                }

        if not zipfile.is_zipfile(zip_path):
            shutil.rmtree(temp_root, ignore_errors=True)
            return {
                "ok": False,
                "staged_dir": "",
                "backups": backup_res["backups"],
                "error": "File tải về không phải định dạng ZIP hợp lệ.",
            }

        if progress_callback:
            progress_callback(92, 100, "Đang giải nén và kiểm tra gói cập nhật...")

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        entries = os.listdir(extract_dir)
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            staged_dir = os.path.join(extract_dir, entries[0])
        else:
            staged_dir = extract_dir

        strip_protected_items(staged_dir)

        valid_pkg, reason = validate_portable_package(staged_dir)
        if not valid_pkg:
            shutil.rmtree(temp_root, ignore_errors=True)
            return {
                "ok": False,
                "staged_dir": "",
                "backups": backup_res["backups"],
                "error": reason,
            }

        if progress_callback:
            progress_callback(100, 100, "Đã kiểm tra hợp lệ và sẵn sàng áp dụng bản cập nhật!")

        return {
            "ok": True,
            "staged_dir": staged_dir,
            "backups": backup_res["backups"],
            "error": None,
        }

    except Exception as e:
        log.error(f"[Updater] ❌ Lỗi tải/giải nén cập nhật: {e}")
        return {"ok": False, "staged_dir": "", "backups": backup_res.get("backups", []), "error": str(e)}


def update_via_git_pull(repo_dir: str) -> dict:
    """Update source code directly via git pull when running from a Git repository (source mode).

    Verifies SQLite backup first and never runs the portable EXE batch script.
    """
    backup_res = backup_user_data(repo_dir)
    if not backup_res["ok"]:
        return {"ok": False, "output": "", "error": backup_res["error"]}

    try:
        env = os.environ.copy()
        git_cmd_dir = r"C:\Program Files\Git\cmd"
        if os.path.isdir(git_cmd_dir) and git_cmd_dir not in env.get("PATH", ""):
            env["PATH"] = f"{git_cmd_dir};{env.get('PATH', '')}"
        env["GIT_TERMINAL_PROMPT"] = "0"

        proc = subprocess.run(
            ["git", "pull", "--ff-only", "origin", "main"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if proc.returncode == 0:
            return {
                "ok": True,
                "output": proc.stdout.strip(),
                "backups": backup_res["backups"],
                "error": None,
            }
        return {
            "ok": False,
            "output": proc.stdout,
            "backups": backup_res["backups"],
            "error": proc.stderr.strip() or "git pull thất bại",
        }
    except Exception as e:
        return {"ok": False, "output": "", "backups": backup_res["backups"], "error": str(e)}


def create_and_run_updater_script(
    staged_source_dir: str,
    target_dir: str,
    exe_name: str = "PackStation.exe",
    wait_pid: Optional[int] = None,
    launch_after: bool = True,
    restart_app: bool = True,
) -> str:
    """Create a safe Windows batch script that:
    1. Verifies the staged package contains `PackStation.exe` before proceeding.
    2. Waits for the old application process (by PID / executable lock) to exit cleanly.
    3. Takes a rollback snapshot of current application binaries/code into `temp_update\\rollback_snapshot`.
    4. Copies new files via `robocopy`, strictly excluding `packstation.db*`, `packstation-config.json*`, `Videos`, `logs`.
    5. Checks `robocopy` exit code (`>= 8` means failure) and verifies `PackStation.exe` exists; if anything failed,
       automatically restores from `rollback_snapshot`, preserves `temp_update` & logs error to `logs\\updater_error.log`.
    """
    valid_pkg, reason = validate_portable_package(staged_source_dir)
    if not valid_pkg:
        raise ValueError(reason)

    script_path = os.path.join(target_dir, "updater_apply.bat")
    temp_root = os.path.join(target_dir, "temp_update")
    rollback_dir = os.path.join(temp_root, "rollback_snapshot")
    log_dir = os.path.join(target_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    err_log_path = os.path.join(log_dir, "updater_error.log")
    exe_path = os.path.join(target_dir, exe_name)
    pid_to_wait = int(wait_pid) if wait_pid else 0
    restart_flag = "1" if restart_app else "0"

    bat_content = f"""@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "STAGED_DIR={staged_source_dir}"
set "TARGET_DIR={target_dir}"
set "TEMP_ROOT={temp_root}"
set "ROLLBACK_DIR={rollback_dir}"
set "EXE_PATH={exe_path}"
set "ERR_LOG={err_log_path}"
set "WAIT_PID={pid_to_wait}"
set "RESTART_APP={restart_flag}"

echo [Updater] Dang cho ung dung cu dong hoan toan...
if not "%WAIT_PID%"=="0" (
    for /L %%i in (1,1,15) do (
        tasklist /FI "PID eq %WAIT_PID%" 2>nul | find /I "%WAIT_PID%" >nul
        if errorlevel 1 goto :process_exited
        ping 127.0.0.1 -n 2 >nul
    )
    echo [Updater] ERROR: Ung dung cu PID %WAIT_PID% chua dong sau 15 giay. Huy cap nhat. >> "%ERR_LOG%"
    exit /b 1
) else (
    ping 127.0.0.1 -n 2 >nul
)
:process_exited

echo [Updater] Dang tao ban sao luu phuc hoi rollback snapshot...
if exist "%ROLLBACK_DIR%" rmdir /s /q "%ROLLBACK_DIR%" 2>nul
mkdir "%ROLLBACK_DIR%" 2>nul
robocopy "%TARGET_DIR%" "%ROLLBACK_DIR%" /E /XF "packstation.db" "packstation.db-wal" "packstation.db-shm" "packstation.db*.backup*" "packstation_backup*.db" "packstation-config.json" "packstation-config.json.backup*" "updater_apply.bat" /XD "Videos" "logs" "temp_update" ".git" >nul
set "SNAP_RC=%ERRORLEVEL%"
if !SNAP_RC! GEQ 8 (
    echo [Updater] ERROR: Khong the tao rollback snapshot - robocopy code !SNAP_RC! >> "%ERR_LOG%"
    exit /b 2
)

echo [Updater] Dang sao chep ban cap nhat moi...
robocopy "%STAGED_DIR%" "%TARGET_DIR%" /E /IS /IT /XF "packstation.db" "packstation.db-wal" "packstation.db-shm" "packstation.db*.backup*" "packstation_backup*.db" "packstation-config.json" "packstation-config.json.backup*" "updater_apply.bat" /XD "Videos" "logs" "temp_update" ".git" >nul
set "COPY_RC=%ERRORLEVEL%"
if !COPY_RC! GEQ 8 (
    echo [Updater] ERROR: Sao chep ban cap nhat that bai - robocopy code !COPY_RC! >> "%ERR_LOG%"
    goto :rollback
)

if not exist "%EXE_PATH%" (
    echo [Updater] ERROR: Khong tim thay PackStation.exe sau khi cap nhat. Dang khoi phuc ban cu... >> "%ERR_LOG%"
    goto :rollback
)

echo [Updater] Cap nhat thanh cong. Dang don dep thu muc tam...
rmdir /s /q "%TEMP_ROOT%" 2>nul
if "%RESTART_APP%"=="1" (
    if exist "%EXE_PATH%" (
        start "" "%EXE_PATH%"
    )
    start "" /b cmd /c "ping 127.0.0.1 -n 2 >nul & del /f /q ""%~f0"" >nul 2>&1"
)
exit /b 0

:rollback
robocopy "%ROLLBACK_DIR%" "%TARGET_DIR%" /E /IS /IT /XF "packstation.db" "packstation.db-wal" "packstation.db-shm" "packstation.db*.backup*" "packstation_backup*.db" "packstation-config.json" "packstation-config.json.backup*" "updater_apply.bat" /XD "Videos" "logs" "temp_update" ".git" >nul
echo [Updater] Da khoi phuc phien ban truoc tu rollback snapshot. Giu nguyen temp_update de kiem tra. >> "%ERR_LOG%"
exit /b 3
"""
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    if launch_after:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.Popen(
            ["cmd.exe", "/c", script_path],
            cwd=target_dir,
            creationflags=creation_flags,
        )

    return script_path
