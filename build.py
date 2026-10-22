"""Build PackStation as a portable exe using PyInstaller.

Includes:
- Version info metadata to reduce antivirus false positives
- Antivirus exclusion script bundled in output
- VC++ and PyZbar DLL bundling
"""
import subprocess
import sys
import os


def create_version_info(base_dir: str) -> str:
    """Create a version info file to embed metadata in the EXE.
    This reduces antivirus false positives by providing publisher info.
    """
    version_file = os.path.join(base_dir, "version_info.txt")
    content = """
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 5, 7, 0),
    prodvers=(1, 5, 7, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'BA DUY - PackStation'),
         StringStruct(u'FileDescription', u'PackStation - Phan mem quan ly dong goi hang hoa'),
         StringStruct(u'FileVersion', u'1.5.7.0'),
         StringStruct(u'InternalName', u'PackStation'),
         StringStruct(u'LegalCopyright', u'Copyright (c) 2024-2026 BA DUY. All rights reserved.'),
         StringStruct(u'OriginalFilename', u'PackStation.exe'),
         StringStruct(u'ProductName', u'PackStation'),
         StringStruct(u'ProductVersion', u'1.5.7.0')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    with open(version_file, "w", encoding="utf-8") as f:
        f.write(content.strip())
    return version_file


def build(dist_root: str = "", sync_to_c_packstation: bool = True):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    # Generate version info to reduce AV false positives
    version_file = create_version_info(base_dir)
    actual_dist_root = dist_root or os.path.join(base_dir, "dist")
    work_root = os.path.join(os.path.dirname(actual_dist_root), "build_work") if dist_root else os.path.join(base_dir, "build")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "PackStation",
        f"--distpath={actual_dist_root}",
        f"--workpath={work_root}",
        f"--specpath={actual_dist_root if dist_root else base_dir}",
        f"--add-data={os.path.join(base_dir, 'i18n')};i18n",
        f"--add-data={os.path.join(base_dir, 'audio')};audio",
        f"--add-data={os.path.join(base_dir, 'assets')};assets",
        f"--add-data={os.path.join(base_dir, 'libs')};libs",
        f"--add-binary={ffmpeg_exe};.",
        f"--version-file={version_file}",
        "--hidden-import=pyzbar",
        "--hidden-import=zxingcpp",
        "--hidden-import=customtkinter",
        "--hidden-import=PIL",
        "--hidden-import=cv2",
        "--hidden-import=openpyxl",
        "--hidden-import=certifi",
        "--collect-data=certifi",
        "--collect-all=customtkinter",
        "--collect-all=pyzbar",
        "--collect-all=zxingcpp",
        os.path.join(base_dir, "main.py"),
    ]

    icon_path = os.path.join(base_dir, "assets", "icon.ico")
    if os.path.exists(icon_path):
        cmd.insert(-1, f"--icon={icon_path}")

    print("🔨 Building PackStation portable...")
    print(f"Command: {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=base_dir)

    if result.returncode == 0:
        print("\n✅ Build thành công!")
        dist_dir = os.path.join(actual_dist_root, "PackStation")
        print(f"📁 Output: {dist_dir}")

        import shutil
        # Ensure VC++ and PyZbar DLLs are bundled in dist_dir
        sys32 = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32")
        for dll in ["msvcp140.dll", "concrt140.dll"]:
            src_dll = os.path.join(sys32, dll)
            if os.path.exists(src_dll):
                shutil.copy2(src_dll, os.path.join(dist_dir, dll))

        for dll in ["libzbar-64.dll", "libiconv.dll"]:
            src_dll = os.path.join(base_dir, "libs", dll)
            if os.path.exists(src_dll):
                shutil.copy2(src_dll, os.path.join(dist_dir, dll))

        # Copy resource directories (i18n, audio, assets, libs) to root of dist_dir
        for folder in ["i18n", "audio", "assets", "libs"]:
            src_f = os.path.join(base_dir, folder)
            dst_f = os.path.join(dist_dir, folder)
            if os.path.exists(src_f):
                shutil.copytree(src_f, dst_f, dirs_exist_ok=True)

        # Copy antivirus setup script
        av_script = os.path.join(base_dir, "setup_antivirus.bat")
        if os.path.exists(av_script):
            shutil.copy2(av_script, os.path.join(dist_dir, os.path.basename(av_script)))

        # Copy standalone video sync & recovery tools
        for tool_f in ["sync_videos.py", "sync_videos.bat"]:
            src_tool = os.path.join(base_dir, tool_f)
            if os.path.exists(src_tool):
                shutil.copy2(src_tool, os.path.join(dist_dir, tool_f))

        # Create logs directory for file logging
        os.makedirs(os.path.join(dist_dir, "logs"), exist_ok=True)

        # Optionally sync to C:\PackStation if enabled
        if sync_to_c_packstation:
            target_portable = r"C:\PackStation"
            try:
                target_db = os.path.join(target_portable, "packstation.db")
                if os.path.exists(target_db):
                    import time
                    from core.updater import backup_sqlite_database
                    backup_db = os.path.join(target_portable, f"packstation_backup_{int(time.time())}.db")
                    bak_res = backup_sqlite_database(target_db, backup_db)
                    ok_bak = bak_res.get("ok") if isinstance(bak_res, dict) else bool(bak_res)
                    err_bak = bak_res.get("error", "") if isinstance(bak_res, dict) else ""
                    if ok_bak:
                        print(f"🛡️ Đã sao lưu Database hiện có (SQLite Backup API): {backup_db}")
                    else:
                        print(f"⚠️ Cảnh báo sao lưu Database: {err_bak}")

                protected_names = {
                    "packstation.db",
                    "packstation.db-wal",
                    "packstation.db-shm",
                    "packstation-config.json",
                    "videos",
                    "logs",
                }
                for item in os.listdir(dist_dir):
                    if item.lower() in protected_names or item.lower().startswith("packstation_backup"):
                        continue
                    s = os.path.join(dist_dir, item)
                    d = os.path.join(target_portable, item)
                    if os.path.isdir(s):
                        shutil.copytree(s, d, dirs_exist_ok=True)
                    else:
                        shutil.copy2(s, d)
                print(f"✅ Đã đồng bộ sang {target_portable}")
            except Exception as e:
                print(f"⚠️ Đồng bộ sang C:\\PackStation: {e}")

        # Cleanup version info file
        if os.path.exists(version_file):
            os.remove(version_file)
    else:
        print(f"\n❌ Build thất bại (code {result.returncode})")
        if os.path.exists(version_file):
            os.remove(version_file)
        sys.exit(result.returncode)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build PackStation portable")
    parser.add_argument("--dist-dir", default="", help="Custom output dist directory")
    parser.add_argument("--no-sync", action="store_true", help="Do not sync build output to C:\\PackStation")
    args = parser.parse_args()
    build(dist_root=args.dist_dir, sync_to_c_packstation=not args.no_sync)
