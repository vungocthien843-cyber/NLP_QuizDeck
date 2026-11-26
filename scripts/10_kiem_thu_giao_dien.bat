@echo off
chcp 65001 >nul
REM KIEM THU GIAO DIEN tu dong (Playwright, trinh duyet Chromium chay trong Docker). KHONG goi LLM, khong ton tien.
REM Tu tao 2 tai khoan thu (__e2e@ictu.edu.vn) va phien dang nhap, chay cac luong: dang nhap, xem slide, lam bai,
REM xem lai, ket qua, quan tri; xong tu xoa du lieu thu. Can chay 0_kiem_thu_tu_dong.bat truoc (he thong dang chay).
REM Lan dau tai image Playwright (~2 GB). Log: eval\logs\kiem_thu_giao_dien_log.txt
cd /d "%~dp0.."
if not exist eval\logs mkdir eval\logs
set LOG=eval\logs\kiem_thu_giao_dien_log.txt
echo ==== BAT DAU %date% %time% ==== > %LOG%
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. Mo Docker Desktop roi chay lai. & pause & exit /b 1 )

echo [1/2] Khoi dong he thong (neu chua chay)...
docker compose up -d >> %LOG% 2>&1
if errorlevel 1 goto :loi
timeout /t 10 /nobreak >nul

echo [2/2] Chay kiem thu giao dien (lan dau tai image Playwright, vai phut)...
docker compose --profile e2e run --rm e2e >> %LOG% 2>&1
set RC=%errorlevel%
echo.
powershell -NoProfile -Command "Get-Content -Encoding UTF8 eval\logs\kiem_thu_giao_dien_log.txt -Tail 4"
echo.
if not %RC%==0 goto :loi
echo GIAO DIEN CHAY DUNG. Mo http://localhost:8080 de dung that.
pause
exit /b 0

:loi
echo ==== LOI ==== >> %LOG%
echo CO LOI. Quay lai Claude va bao "loi giao dien" (log: eval\logs\kiem_thu_giao_dien_log.txt).
pause
exit /b 1
