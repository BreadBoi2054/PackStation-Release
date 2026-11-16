@echo off
chcp 65001 >nul
title PackStation - Đồng bộ video từ thư mục
cd /d "%~dp0"
echo ==================================================
echo  PACKSTATION - KHÔI PHỤC VÀ ĐỒNG BỘ VIDEO TỪ THƯ MỤC
echo ==================================================
if exist "%~dp0PackStation.exe" (
    "%~dp0PackStation.exe" --sync-videos
) else (
    python "%~dp0sync_videos.py"
)
echo.
pause
