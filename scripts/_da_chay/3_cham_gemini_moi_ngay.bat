@echo off
chcp 65001 >nul
REM Cham bang Gemini (goi MIEN PHI): 40 slide chung, V1 va V3, 1 solver (flash) + giam khao (pro).
REM Goi cham theo han muc moi phut; HET HAN MUC NGAY thi tu dung. Moi ngay nhap dup 1 lan cho toi khi bao "DA CHAM XONG".
REM Ket qua da cham luu dem (eval\quality\cache), chay lai khong mat. Log: eval\logs\gemini_log.txt
cd /d "%~dp0..\.."
if not exist eval\logs mkdir eval\logs
if not exist backups mkdir backups
set LOG=eval\logs\gemini_log.txt
echo ==== BAT DAU %date% %time% ==== >> %LOG%
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )
docker compose up -d >nul 2>&1
timeout /t 15 /nobreak >nul
set RES=eval/v2/results/G1
set DATA=eval/quality/data_g1
if exist eval\v2\results\NLP\questions_C5.jsonl set RES=eval/v2/results/NLP
if exist eval\v2\results\NLP\questions_C5.jsonl set DATA=eval/quality/data_nlp
echo Bo du lieu: %DATA%
echo Dang cham (co the mat 1-2 gio vi phai goi cham)... theo doi: eval\logs\gemini_log.txt
docker compose exec -T api python -m eval.quality.run_eval --data %DATA% --layers A S J --versions V1 V3 --sample 40 --solvers gemini/gemini-flash-latest --runs 1 >> %LOG% 2>&1
set RC=%errorlevel%
if %RC%==3 (
  echo.
  echo HET HAN MUC GEMINI HOM NAY. Phan da cham duoc giu lai. NGAY MAI nhap dup lai file nay de cham tiep.
  pause
  exit /b 0
)
if not %RC%==0 (
  echo.
  echo CO LOI - quay lai Claude va bao "loi".
  pause
  exit /b 1
)
echo.
docker compose exec -T api python -m eval.tong_hop --data %DATA% >nul 2>&1
echo DA CHAM XONG (da cap nhat eval\BAO_CAO_DANH_GIA.md). Quay lai Claude va bao "xong".
pause
