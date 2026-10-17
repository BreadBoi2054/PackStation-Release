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
    filevers=(1, 5, 5, 0),
    prodvers=(1, 5, 5, 0),
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
         StringStruct(u'FileVersion', u'1.5.5.0'),
         StringStruct(u'InternalName', u'PackStation'),
         StringStruct(u'LegalCopyright', u'Copyright (c) 2024-2026 BA DUY. All rights reserved.'),
         StringStruct(u'OriginalFilename', u'PackStation.exe'),
         StringStruct(u'ProductName', u'PackStation'),
         StringStruct(u'ProductVersion', u'1.5.5.0')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    with open(version_file, "w", encoding="utf-8") as f:
        f.write(content.strip())
    return version_file


def build():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    # Generate version info to reduce AV false positives
    version_file = create_version_info(base_dir)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "PackStation",
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
        dist_dir = os.path.join(base_dir, "dist", "PackStation")
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

        # Also sync to C:\PackStation
        target_portable = r"C:\PackStation"
        try:
            # Backup existing database in C:\PackStation if present
            target_db = os.path.join(target_portable, "packstation.db")
            if os.path.exists(target_db):
                import time
                backup_db = os.path.join(target_portable, f"packstation_backup_{int(time.time())}.db")
                try:
                    shutil.copy2(target_db, backup_db)
                    print(f"🛡️ Đã sao lưu Database hiện có: {backup_db}")
                except Exception:
                    pass

            for item in os.listdir(dist_dir):
                # NEVER overwrite user database in target directory!
                if item.lower() == "packstation.db":
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

if __name__ == "__main__":
    build()
