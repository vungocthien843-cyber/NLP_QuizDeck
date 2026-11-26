@echo off
chcp 65001 >nul
REM Dong thu nghiem sinh vien: khung "Thu nghiem" bien mat khoi giao dien. Du lieu lam bai VAN GIU (phan tich lai duoc).
cd /d "%~dp0.."
if not exist eval\logs mkdir eval\logs
if not exist backups mkdir backups
docker compose exec -T api python -m eval.student.chuan_bi --close
echo.
echo Phan tich lai sau khi dong: scripts\8_thu_nghiem_sv_phan_tich.bat eval/student/data/thu_nghiem_dong_....json
pause
