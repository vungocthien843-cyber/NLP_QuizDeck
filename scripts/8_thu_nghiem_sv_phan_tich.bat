@echo off
chcp 65001 >nul
REM Moc 3 - Buoc 3: phan tich thu nghiem sinh vien. Chay duoc nhieu lan (ca khi dang thu nghiem).
cd /d "%~dp0.."
if not exist eval\logs mkdir eval\logs
if not exist backups mkdir backups
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )
docker compose up -d >nul 2>&1
docker compose exec -T api python -c "import sklearn, scipy" >nul 2>&1 || docker compose exec -T api pip install -q scikit-learn scipy
set CFG=
if not "%~1"=="" set CFG=--config %~1
docker compose exec -T api python -m eval.student.phan_tich %CFG%
if errorlevel 1 ( echo. & echo CO LOI - chup man hinh gui Claude. & pause & exit /b 1 )
echo.
echo XONG. Bao cao: eval\student\results\bao_cao_sinh_vien.md
pause
