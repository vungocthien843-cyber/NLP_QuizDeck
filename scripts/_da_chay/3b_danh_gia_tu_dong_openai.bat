@echo off
chcp 65001 >nul
REM BO DANH GIA TU DONG DAY DU, CHAM NGAY bang OpenAI (khong cho han muc Gemini). CO PHI: uoc tinh 1-5 USD (~1.500 lan goi).
REM   1) Xuat lai du lieu (bo NLP 9 chuong neu da tao bang 2b, neu chua thi G1) (kem nhan hieu nham, ablation nguon sinh V3-chi-ViT5 / V3-chi-LLM)
REM   2) Lop A + E cho moi phien ban va moi bien the ablation (tai may, mien phi)
REM   3) Lop S + J (nguoi giai + giam khao = openai/gpt-6-sol, khac model sinh gpt-6-luna) cho V1 va V3
REM   4) Bao cao tong hop 3 tang: eval\BAO_CAO_DANH_GIA.md
REM Ket qua da cham duoc luu dem: chay lai khong ton them tien cho phan da xong. Log: eval\logs\danh_gia_openai_log.txt
cd /d "%~dp0..\.."
if not exist eval\logs mkdir eval\logs
set LOG=eval\logs\danh_gia_openai_log.txt
echo ==== BAT DAU %date% %time% ==== > %LOG%
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )
docker compose up -d >nul 2>&1
timeout /t 15 /nobreak >nul
set RES=eval/v2/results/G1
set DATA=eval/quality/data_g1
if exist eval\v2\results\NLP\questions_C5.jsonl set RES=eval/v2/results/NLP
if exist eval\v2\results\NLP\questions_C5.jsonl set DATA=eval/quality/data_nlp
echo Bo du lieu: %DATA%

echo [1/4] Xuat lai du lieu G1...
docker compose exec -T api python -m eval.quality.export --results %RES% --out %DATA% >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [2/4] Lop A + E cho moi phien ban (~10 phut)...
docker compose exec -T api python -m eval.quality.run_eval --data %DATA% --layers A E >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [3/4] Lop S + J bang OpenAI cho V1 va V3 (~20-40 phut, co phi)...
docker compose exec -T api python -m eval.quality.run_eval --data %DATA% --layers A S J --versions V1 V3 --judge openai/gpt-6-sol --solvers openai/gpt-6-sol --runs 1 >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [4/4] Bao cao tong hop...
docker compose exec -T api python -m eval.tong_hop --data %DATA% >> %LOG% 2>&1
if errorlevel 1 goto :loi
echo.
echo XONG. Mo eval\BAO_CAO_DANH_GIA.md. Quay lai Claude va bao "xong".
pause
exit /b 0
:loi
echo.
echo CO LOI - quay lai Claude va bao "loi" (log: %LOG%).
pause
exit /b 1
