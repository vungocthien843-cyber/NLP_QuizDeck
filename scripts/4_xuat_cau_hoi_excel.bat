@echo off
chcp 65001 >nul
REM Xuat toan bo cau hoi cua bo danh gia ra 1 file Excel de kiem tra: cau hoi, 4 phuong an, dap an dung (to xanh),
REM giai thich, cau trich lam can cu, noi dung slide; V3 kem loai hieu nham + nguon sinh cua tung phuong an sai.
REM Dung bo NLP 9 chuong neu da tao (scripts\_da_chay\2b), neu chua thi G1. Khong goi API.
cd /d "%~dp0.."
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )
docker compose up -d >nul 2>&1
set RES=eval/v2/results/G1
set DATA=eval/quality/data_g1
if exist eval\quality\data_nlp\V3_items.jsonl set RES=eval/v2/results/NLP
if exist eval\quality\data_nlp\V3_items.jsonl set DATA=eval/quality/data_nlp
docker compose exec -T api sh -c "pip install -q openpyxl >/dev/null 2>&1"
docker compose exec -T api python -m eval.xuat_cau_hoi --data %DATA% --results %RES%
if errorlevel 1 ( echo CO LOI - chup man hinh gui Claude. & pause & exit /b 1 )
echo.
echo XONG: file cau_hoi_*.xlsx nam trong thu muc %RES%
pause
