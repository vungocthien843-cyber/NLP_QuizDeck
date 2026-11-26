@echo off
chcp 65001 >nul
REM CHAY SAU FILE 1. CHAM M1, M2 (lop S) va M1b (giam khao chi prompt P2) cho V3 + doi chung LLM-GPT bang OpenAI
REM (moc so sanh = LLM-GPT, khong cham V1 nua). CO TRAN CHI PHI: lop S toi da 1,28 USD + P2 toi da 0,42 USD.
REM (Do that 17/11: ~0,0021 USD / lan goi -> lop S ~1,23 USD, P2 ~0,41 USD.) 10 cau da cham thu lay tu bo dem, khong tra lai.
REM Cham tran thi tu dung, phan da cham duoc giu. Log: eval\logs\cham_ngan_sach_log.txt
cd /d "%~dp0.."
if not exist eval\logs mkdir eval\logs
set LOG=eval\logs\cham_ngan_sach_log.txt
echo ==== BAT DAU %date% %time% ==== > %LOG%
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )
docker compose up -d >nul 2>&1
timeout /t 15 /nobreak >nul
set DATA=eval/quality/data_nlp
if not exist eval\quality\data_nlp\LLM-GPT_items.jsonl ( echo Chua co doi chung LLM-GPT: chay scripts\1_sinh_doi_chung_llm.bat truoc. & pause & exit /b 1 )

echo [1/3] Lop S (M1, M2) cho V3 + LLM-GPT, tran 1,28 USD (~20-30 phut)...
docker compose exec -T api python -m eval.quality.run_eval --data %DATA% --layers A S --versions V3 LLM-GPT --base LLM-GPT --solvers openai/gpt-6-sol --runs 1 --max-usd 1.28 >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [2/3] Giam khao P2 (M1b: cau co 2 dap an dung), tran 0,42 USD (~10 phut)...
docker compose exec -T api python -m eval.quality.run_eval --data %DATA% --layers A J --versions V3 LLM-GPT --base LLM-GPT --judge openai/gpt-6-sol --judge-prompts P2 --runs 1 --max-usd 0.42 >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [3/3] Bao cao tong hop...
docker compose exec -T api python -m eval.tong_hop --data %DATA% >> %LOG% 2>&1
echo.
powershell -NoProfile -Command "Get-Content -Encoding UTF8 eval\logs\cham_ngan_sach_log.txt | Select-String -Pattern 'USD' | Select-Object -Last 8"
echo.
echo XONG. Mo eval\BAO_CAO_DANH_GIA.md. Quay lai Claude va bao "xong".
pause
exit /b 0
:loi
echo.
echo CO LOI - quay lai Claude va bao "loi" (log: %LOG%).
pause
exit /b 1
