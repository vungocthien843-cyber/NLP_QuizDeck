@echo off
chcp 65001 >nul
REM CHAY THU DE BIET CHI PHI truoc khi cham toan bo bang OpenAI.
REM Cham 5 slide (5 cau V1 + 5 cau V3 = 10 cau, khoang 80 lan goi gpt-6-sol), roi in chi phi THAT va UOC TINH cho toan bo.
REM Chi phi lan thu: duoi khoang 0,2 USD. Ket qua da cham duoc luu dem: chay toan bo sau do khong tra lai tien cho 10 cau nay.
cd /d "%~dp0..\.."
if not exist eval\logs mkdir eval\logs
set LOG=eval\logs\thu_chi_phi_log.txt
echo ==== BAT DAU %date% %time% ==== > %LOG%
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )
docker compose up -d >nul 2>&1
timeout /t 15 /nobreak >nul
set DATA=eval/quality/data_g1
if exist eval\quality\data_nlp\V3_items.jsonl set DATA=eval/quality/data_nlp
echo Dang cham thu 10 cau tren %DATA% (vai phut)...
docker compose exec -T api python -m eval.quality.run_eval --data %DATA% --layers A S J --versions V1 V3 --sample 5 --judge openai/gpt-6-sol --solvers openai/gpt-6-sol --runs 1 >> %LOG% 2>&1
set RC=%errorlevel%
echo.
powershell -NoProfile -Command "$t = Get-Content -Encoding UTF8 eval\logs\thu_chi_phi_log.txt; $i = ($t | Select-String -Pattern 'CHI PHÍ' | Select-Object -Last 1).LineNumber; if ($i) { $t[($i-1)..($i+8)] } else { $t | Select-Object -Last 15 }"
echo.
if not %RC%==0 ( echo CO LOI - quay lai Claude va bao "loi". & pause & exit /b 1 )
echo XONG. Chup man hinh phan CHI PHI o tren gui Claude.
pause
