@echo off
chcp 65001 >nul
REM Moc 3 - Buoc 3: chuan bi thu nghiem sinh vien (G4/G5). Chay khi da co bo cau hoi.
REM Xem eval\student\kich_ban_thu_nghiem.md. Log: eval\logs\student_log.txt
cd /d "%~dp0.."
if not exist eval\logs mkdir eval\logs
if not exist backups mkdir backups
set LOG=eval\logs\student_log.txt
echo ==== BAT DAU %date% %time% ==== > %LOG%
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. Mo Docker Desktop roi chay lai. & pause & exit /b 1 )
docker compose up -d >> %LOG% 2>&1
timeout /t 15 /nobreak >nul

echo [1/4] Sao luu database truoc migration 004...
docker compose exec -T db sh -c "pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc -f /tmp/truoc_004.dump" >> %LOG% 2>&1
if errorlevel 1 goto :loi
docker compose cp db:/tmp/truoc_004.dump ./backups/truoc_004.dump >> %LOG% 2>&1

echo [2/4] Migration 004 (bang feedback, trang thai cau 'experiment')...
docker compose exec -T db sh -c "psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/004_experiment.sql" >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [3/4] Build lai API va giao dien (vai phut)...
docker compose up -d --build >> %LOG% 2>&1
if errorlevel 1 goto :loi
timeout /t 30 /nobreak >nul

echo [4/4] Nhap cau hoi, tao 2 de, chia nhom (goi LLM gan nhan cau V1, vai xu)...
set RES=eval/v2/results/G1
set DATA=eval/quality/data_g1
if exist eval\quality\data_nlp\V3_items.jsonl set RES=eval/v2/results/NLP
if exist eval\quality\data_nlp\V3_items.jsonl set DATA=eval/quality/data_nlp
if exist eval\student\ma_lop.txt (
  docker compose exec -T api python -m eval.student.chuan_bi --results %RES% --codes eval/student/ma_lop.txt >> %LOG% 2>&1
) else (
  docker compose exec -T api python -m eval.student.chuan_bi --results %RES% >> %LOG% 2>&1
)
if errorlevel 1 goto :loi
powershell -NoProfile -Command "Get-Content -Encoding UTF8 eval\logs\student_log.txt -Tail 7"
echo.
echo XONG. Phat ma trong eval\student\data\phat_ma_sinh_vien.csv. Quay lai Claude va bao "xong".
pause
exit /b 0

:loi
echo ==== LOI (errorlevel %errorlevel%) ==== >> %LOG%
echo.
echo CO LOI - da dung lai. Quay lai Claude va bao "loi".
pause
exit /b 1
