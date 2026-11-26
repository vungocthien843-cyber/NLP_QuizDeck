@echo off
chcp 65001 >nul
REM Moc 3 - Buoc 2: phan tich phieu cham nguoi da dien (kappa, so sanh V1 - V3, do chinh xac nhan LLM).
REM Truoc khi chay: chep cac file phieu_*_nguoi1.csv / phieu_*_nguoi2.csv da dien vao eval\human_v3\data
cd /d "%~dp0.."
if not exist eval\logs mkdir eval\logs
if not exist backups mkdir backups
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )
docker compose up -d >nul 2>&1
docker compose exec -T api python -c "import sklearn, scipy, openpyxl" >nul 2>&1 || docker compose exec -T api pip install -q scikit-learn scipy openpyxl
docker compose exec -T api python -m eval.human_v3.phan_tich
if errorlevel 1 ( echo. & echo Phieu con o thieu/sai - xem danh sach o tren, sua roi chay lai. & pause & exit /b 1 )
echo.
echo XONG. Bao cao: eval\human_v3\results\bao_cao_nguoi.md
pause
