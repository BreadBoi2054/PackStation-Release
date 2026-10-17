"""Auto-updater module for PackStation.

Supports:
1. Checking latest release from GitHub Releases API (BreadBoi2054/PackStation-Release).
2. Safe downloading and staging of portable Windows ZIP release with progress reporting.
3. Strict preservation of user data (packstation.db, packstation-config.json, Videos/, logs/).
4. Automatic database & config backup before applying update.
5. Self-updating batch runner for frozen PyInstaller EXE and git pull support for source mode.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from typing import Callable, Optional

from core.logger import get_logger

log = get_logger()

CURRENT_VERSION = "v1.5.4"
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
}


def parse_version(version_str: str) -> tuple:
    """Parse version string like 'v1.5.4' or '1.5.4.0' into integer tuple (1, 5, 4)."""
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


def check_for_update(
    repo: str = GITHUB_REPO,
    current_version: str = CURRENT_VERSION,
    timeout: int = 10,
) -> dict:
    """Check GitHub Releases API for a newer version of PackStation."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PackStation-Updater",
    }
    result = {
        "has_update": False,
        "current_version": current_version,
        "latest_version": current_version,
        "release_name": "",
        "release_notes": "",
        "html_url": f"https://github.com/{repo}/releases",
        "download_url": "",
        "asset_name": "",
        "asset_size": 0,
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

        # Find ZIP asset
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.lower().endswith(".zip"):
                result["download_url"] = asset.get("browser_download_url", "")
                result["asset_name"] = name
                result["asset_size"] = int(asset.get("size", 0))
                break

        # Fallback to zipball_url if no binary zip asset is attached
        if not result["download_url"] and data.get("zipball_url"):
            result["download_url"] = data.get("zipball_url")
            result["asset_name"] = f"PackStation-{tag_name}.zip"

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


def backup_user_data(target_dir: str) -> list:
    """Create safety backups of packstation.db and packstation-config.json before updating."""
    backed_up = []
    ts = int(time.time())
    for filename in ("packstation.db", "packstation-config.json"):
        src = os.path.join(target_dir, filename)
        if os.path.exists(src):
            bak_name = f"{filename}.backup_{ts}"
            dst = os.path.join(target_dir, bak_name)
            try:
                shutil.copy2(src, dst)
                backed_up.append(dst)
                log.info(f"[Updater] 🛡️ Đã sao lưu dữ liệu trước cập nhật: {dst}")
            except Exception as e:
                log.warning(f"[Updater] ⚠️ Không thể tạo bản sao lưu {filename}: {e}")
    return backed_up


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


def download_and_stage_update(
    download_url: str,
    target_dir: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    timeout: int = 60,
) -> dict:
    """Download the release ZIP, extract it to temp_update, and strip protected files.

    Returns dict: {"ok": bool, "staged_dir": str, "backups": list, "error": str|None}
    """
    temp_root = os.path.join(target_dir, "temp_update")
    zip_path = os.path.join(temp_root, "update_package.zip")
    extract_dir = os.path.join(temp_root, "extracted")

    try:
        if os.path.exists(temp_root):
            shutil.rmtree(temp_root, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)

        if progress_callback:
            progress_callback(0, 100, "Đang kết nối tải bản cập nhật...")

        headers = {"User-Agent": "PackStation-Updater"}
        req = urllib.request.Request(download_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 256 * 1024  # 256 KB

            with open(zip_path, "wb") as out_file:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        mb_done = downloaded / (1024 * 1024)
                        if total_size > 0:
                            mb_total = total_size / (1024 * 1024)
                            pct = min(90, int(downloaded * 90 / total_size))
                            progress_callback(
                                pct, 100, f"Đang tải: {mb_done:.1f} / {mb_total:.1f} MB ({pct}%)"
                            )
                        else:
                            progress_callback(50, 100, f"Đang tải: {mb_done:.1f} MB...")

        if not zipfile.is_zipfile(zip_path):
            return {"ok": False, "staged_dir": "", "backups": [], "error": "File tải về không phải định dạng ZIP hợp lệ."}

        if progress_callback:
            progress_callback(92, 100, "Đang giải nén gói cập nhật...")

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # Determine inner root directory if ZIP contains a single top-level folder (e.g., PackStation/)
        entries = os.listdir(extract_dir)
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            staged_dir = os.path.join(extract_dir, entries[0])
        else:
            staged_dir = extract_dir

        if progress_callback:
            progress_callback(96, 100, "Đang sao lưu dữ liệu và kiểm tra an toàn...")

        backups = backup_user_data(target_dir)
        strip_protected_items(staged_dir)

        if progress_callback:
            progress_callback(100, 100, "Đã sẵn sàng áp dụng bản cập nhật!")

        return {
            "ok": True,
            "staged_dir": staged_dir,
            "backups": backups,
            "error": None,
        }

    except Exception as e:
        log.error(f"[Updater] ❌ Lỗi tải/giải nén cập nhật: {e}")
        return {"ok": False, "staged_dir": "", "backups": [], "error": str(e)}


def update_via_git_pull(repo_dir: str) -> dict:
    """Update source code directly via git pull when running from a Git repository."""
    try:
        backup_user_data(repo_dir)
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
            return {"ok": True, "output": proc.stdout.strip(), "error": None}
        return {"ok": False, "output": proc.stdout, "error": proc.stderr.strip() or "git pull thất bại"}
    except Exception as e:
        return {"ok": False, "output": "", "error": str(e)}


def create_and_run_updater_script(
    staged_source_dir: str,
    target_dir: str,
    exe_name: str = "PackStation.exe",
    launch_after: bool = True,
) -> str:
    """Create a Windows batch script that waits for PackStation to close, copies new files safely, and restarts."""
    script_path = os.path.join(target_dir, "updater_apply.bat")
    temp_root = os.path.join(target_dir, "temp_update")
    exe_path = os.path.join(target_dir, exe_name)

    # Use robocopy with explicit exclusion of database, config, Videos, and logs
    bat_content = f"""@echo off
chcp 65001 >nul
echo Dang cap nhat PackStation, vui long doi trong giay lat...
timeout /t 2 /nobreak >nul
robocopy "{staged_source_dir}" "{target_dir}" /E /IS /IT /XF "packstation.db" "packstation.db-wal" "packstation.db-shm" "packstation.db*.backup*" "packstation_backup*.db" "packstation-config.json" "packstation-config.json.backup*" "updater_apply.bat" /XD "Videos" "logs" "temp_update" ".git" >nul
rmdir /s /q "{temp_root}" 2>nul
if exist "{exe_path}" (
    start "" "{exe_path}"
)
del "%~f0"
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
