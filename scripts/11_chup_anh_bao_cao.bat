@echo off
chcp 65001 >nul
REM CHUP ANH GIAO DIEN cho bao cao (muc 3.8). Anh luu vao bao_cao\images\gd_*.png (ghi de neu da co).
REM Tao 2 tai khoan tam, lam vai de, hoi tro ly 1 cau (goi OpenAI 1 lan, vai phan nghin USD), chup anh roi xoa du lieu tam.
REM Can chay 0_kiem_thu_tu_dong.bat truoc (he thong dang chay). Log: eval\logs\chup_anh_log.txt
cd /d "%~dp0.."
if not exist eval\logs mkdir eval\logs
set LOG=eval\logs\chup_anh_log.txt
echo ==== BAT DAU %date% %time% ==== > %LOG%
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. Mo Docker Desktop roi chay lai. & pause & exit /b 1 )

echo [1/2] Khoi dong he thong (neu chua chay)...
docker compose up -d >> %LOG% 2>&1
if errorlevel 1 goto :loi
timeout /t 10 /nobreak >nul

echo [2/2] Chup anh (khoang 1-2 phut)...
docker compose --profile e2e run --rm -v "%cd%\bao_cao\images:/out" e2e sh -c "python -m pip install -q --root-user-action=ignore -r requirements.txt && python chup_anh.py" >> %LOG% 2>&1
set RC=%errorlevel%
echo.
powershell -NoProfile -Command "Get-Content -Encoding UTF8 eval\logs\chup_anh_log.txt -Tail 12"
echo.
if not %RC%==0 goto :loi
echo XONG. Anh nam trong bao_cao\images (gd_1 ... gd_9). Quay lai Claude va bao "da chup".
pause
exit /b 0

:loi
echo ==== LOI ==== >> %LOG%
echo CO LOI. Quay lai Claude va bao "loi chup anh" (log: eval\logs\chup_anh_log.txt).
pause
exit /b 1
