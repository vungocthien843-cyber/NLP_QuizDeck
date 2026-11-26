@echo off
chcp 65001 >nul
REM DOI CHUNG "LLM TRUC TIEP": dua cho LLM CUNG slide + cau hoi + dap an dung cua V3, chi xin 3 phuong an nhieu (1 lan goi).
REM   LLM-GPT    = openai/gpt-6-luna (cung mo hinh sinh cua V3), tran 0,08 USD (uoc ~0,02-0,05 USD)
REM   LLM-Gemini = gemini-flash (goi mien phi, ~15 phut). Het han muc ngay thi chay lai hom sau, tu tiep tuc.
REM Sau do cham MIEN PHI lop A + E (M3, M3b, M4, M4b, M5, M5b, M5c) cho V1, V3, LLM-GPT, LLM-Gemini.
REM Log: eval\logs\doi_chung_log.txt
cd /d "%~dp0.."
if not exist eval\logs mkdir eval\logs
set LOG=eval\logs\doi_chung_log.txt
echo ==== BAT DAU %date% %time% ==== > %LOG%
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )
docker compose up -d >nul 2>&1
timeout /t 15 /nobreak >nul
set DATA=eval/quality/data_nlp

echo [1/4] Sinh doi chung LLM-GPT (gpt-6-luna, ~5 phut)...
docker compose exec -T api python -m eval.baseline_llm --data %DATA% --model openai/gpt-6-luna --name LLM-GPT --max-usd 0.08 >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [2/4] Sinh doi chung LLM-Gemini (gemini-flash, mien phi, ~15 phut)...
docker compose exec -T api python -m eval.baseline_llm --data %DATA% --model gemini/gemini-flash-latest --name LLM-Gemini --rpm 8 >> %LOG% 2>&1
if errorlevel 1 echo   (Gemini dung som - xem log; van cham tiep phan da co)

echo [3/4] Cham mien phi lop A + E cho V1, V3, LLM-GPT, LLM-Gemini...
docker compose exec -T api python -m eval.quality.run_eval --data %DATA% --layers A E --versions V1 V3 LLM-GPT LLM-Gemini >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [4/4] Bao cao tong hop...
docker compose exec -T api python -m eval.tong_hop --data %DATA% >> %LOG% 2>&1
echo.
powershell -NoProfile -Command "Get-Content -Encoding UTF8 %LOG% | Select-String -Pattern 'LLM-.*cau|USD|Dung som' | Select-Object -Last 6"
echo.
echo XONG. Quay lai Claude va bao "xong".
pause
exit /b 0
:loi
echo.
echo CO LOI - quay lai Claude va bao "loi" (log: %LOG%).
pause
exit /b 1
