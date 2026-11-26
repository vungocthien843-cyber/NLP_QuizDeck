@echo off
chcp 65001 >nul
REM Sua lech do dai cua V3 (key ngan nhat 41%%): chon lai bo 3 tu kho ung vien da luu, KHONG sinh lai, KHONG ton API.
REM Sau do xuat lai du lieu va tinh lai chi so tu dong A + E. Khoang 10-15 phut. Log: eval\logs\chon_lai_log.txt
cd /d "%~dp0..\.."
if not exist eval\logs mkdir eval\logs
if not exist backups mkdir backups
set LOG=eval\logs\chon_lai_log.txt
echo ==== BAT DAU %date% %time% ==== > %LOG%
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )

echo [1/4] Build lai API (code chon bo 3 da sua)...
docker compose up -d --build >> %LOG% 2>&1
if errorlevel 1 goto :loi
timeout /t 30 /nobreak >nul

echo [2/4] Chon lai bo 3 cho V3 (C5)...
docker compose exec -T api python -m eval.v2.reselect --results eval/v2/results/G1 >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [3/4] Xuat lai du lieu cham diem...
docker compose exec -T api python -m eval.quality.export --results eval/v2/results/G1 --out eval/quality/data_g1 >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [4/4] Chi so tu dong A + E cho moi phien ban...
docker compose exec -T api python -m eval.quality.run_eval --data eval/quality/data_g1 --layers A E >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo.
echo XONG. Quay lai Claude va bao "xong".
pause
exit /b 0
:loi
echo CO LOI - quay lai Claude va bao "loi".
pause
exit /b 1
