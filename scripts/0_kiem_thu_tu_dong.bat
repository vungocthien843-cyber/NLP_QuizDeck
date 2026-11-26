@echo off
chcp 65001 >nul
REM KIEM THU TU DONG toan he thong. KHONG goi Gemini, KHONG goi OpenAI, khong ton tien.
REM Gom: build lai, migration 004-006 (dang nhap Google, phan quyen tai lieu) (an toan khi chay lai, co sao luu truoc), test don vi + test tich hop tren DB that
REM (tu tao du lieu thu __test_...__ roi tu xoa). Khoang 5-10 phut. Log: eval\logs\kiem_thu_log.txt
cd /d "%~dp0.."
if not exist eval\logs mkdir eval\logs
if not exist backups mkdir backups
set LOG=eval\logs\kiem_thu_log.txt
echo ==== BAT DAU %date% %time% ==== > %LOG%
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. Mo Docker Desktop, cho "Engine running" roi chay lai. & pause & exit /b 1 )

echo [1/4] Build lai va khoi dong (vai phut)...
docker compose up -d --build --remove-orphans >> %LOG% 2>&1
if errorlevel 1 goto :loi
timeout /t 30 /nobreak >nul

echo [2/4] Sao luu DB va chay migration 004, 005, 006 (bo qua neu da chay)...
docker compose exec -T db sh -c "pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc -f /tmp/truoc_kiem_thu.dump" >> %LOG% 2>&1
docker compose cp db:/tmp/truoc_kiem_thu.dump ./backups/truoc_kiem_thu.dump >> %LOG% 2>&1
docker compose exec -T db sh -c "psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/004_experiment.sql" >> %LOG% 2>&1
if errorlevel 1 goto :loi
docker compose exec -T db sh -c "psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/005_auth.sql" >> %LOG% 2>&1
if errorlevel 1 goto :loi
docker compose exec -T db sh -c "psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/006_doc_owner.sql" >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [3/4] Cai cong cu test...
docker compose cp tests api:/app/tests >> %LOG% 2>&1
docker compose exec -T api sh -c "pip install -q pytest httpx scikit-learn scipy openpyxl >/dev/null 2>&1" >> %LOG% 2>&1

echo [4/4] Chay toan bo test (don vi + tich hop)...
docker compose exec -T api sh -c "cd /app && TEST_DATABASE_URL=$DATABASE_URL python -m pytest -q -p no:cacheprovider tests" >> %LOG% 2>&1
set RC=%errorlevel%
echo.
powershell -NoProfile -Command "Get-Content -Encoding UTF8 eval\logs\kiem_thu_log.txt -Tail 4"
echo.
if not %RC%==0 goto :loi
echo TAT CA TEST DEU QUA. Tiep theo: chay 10_kiem_thu_giao_dien.bat, roi mo http://localhost:8080 de thu tay.
pause
exit /b 0

:loi
echo ==== LOI ==== >> %LOG%
echo CO TEST LOI hoac buoc bi loi. Quay lai Claude va bao "loi" (log: eval\logs\kiem_thu_log.txt).
pause
exit /b 1
