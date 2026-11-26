@echo off
chcp 65001 >nul
REM Moc 3 - Buoc 2: tao phieu cham nguoi (G2 + G3). PHIEU DA TAO SAN ngay 16/11 cho Bui Minh Anh va Le Dinh Trung:
REM eval\human_v3\data\gui_Bui_Minh_Anh, gui_Le_Dinh_Trung. Chi chay lai khi muon tao lai (them --force, MAT diem da cham).
cd /d "%~dp0.."
if not exist eval\logs mkdir eval\logs
if not exist backups mkdir backups
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )
docker compose up -d >nul 2>&1
docker compose exec -T api sh -c "pip install -q openpyxl >/dev/null 2>&1"
REM Mac dinh dung bo NLP 9 chuong neu da tao (scripts\_da_chay\2b), neu chua thi G1. Tao lai phieu: them --force vao cuoi lenh.
set RES=eval/v2/results/G1
set DATA=eval/quality/data_g1
if exist eval\quality\data_nlp\V3_items.jsonl set RES=eval/v2/results/NLP
if exist eval\quality\data_nlp\V3_items.jsonl set DATA=eval/quality/data_nlp
docker compose exec -T api python -m eval.human_v3.tao_phieu --data %DATA% --results %RES% --ten "Bùi Minh Ảnh" "Lê Đình Trung"
if errorlevel 1 ( echo. & echo CO LOI - chup man hinh gui Claude. & pause & exit /b 1 )
echo.
echo XONG. Mo thu muc eval\human_v3\data de lay phieu.
pause
