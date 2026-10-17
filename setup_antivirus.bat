@echo off
:: ============================================================
:: PackStation - Cai dat Windows Defender Exclusion
:: Chay file nay voi quyen Admin truoc khi su dung PackStation
:: ============================================================
echo.
echo =====================================================
echo  PACKSTATION - Cai dat Antivirus Exclusion
echo =====================================================
echo.
echo Dang them thu muc PackStation vao danh sach an toan...
echo (Can chay voi quyen Administrator)
echo.

:: Check if running as admin
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [!] Can chay voi quyen Administrator!
    echo     Nhan chuot phai vao file nay va chon "Run as administrator"
    echo.
    pause
    exit /b 1
)

:: Add folder exclusions for Windows Defender
powershell -Command "Add-MpPreference -ExclusionPath 'C:\PackStation'" 2>nul
powershell -Command "Add-MpPreference -ExclusionPath '%~dp0'" 2>nul

:: Add process exclusion
powershell -Command "Add-MpPreference -ExclusionProcess 'PackStation.exe'" 2>nul

echo.
echo [OK] Da them thanh cong cac exclusion:
echo     - Thu muc: C:\PackStation
echo     - Thu muc: %~dp0
echo     - Process: PackStation.exe
echo.
echo PackStation se khong bi Windows Defender chan nua.
echo Ban co the chay PackStation.exe binh thuong.
echo.
pause
