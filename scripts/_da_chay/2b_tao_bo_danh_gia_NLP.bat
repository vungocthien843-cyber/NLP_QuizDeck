@echo off
chcp 65001 >nul
REM TAO BO DU LIEU DANH GIA MOI TU TOAN BO 9 CHUONG NLP (thay cho G1: G1 chi co chuong 4 + bai 1 CV, chuong 9 bi bo sot).
REM   - Chon moi bai co ten file chua "Chuong" (9 chuong NLP), 12 slide hat giong MOI chuong (~108), bo slide tieu de
REM     va slide hanh chinh (lo trinh, muc tieu, tai lieu tham khao, cam on).
REM   - Sinh cau bang V1 (C0) va V3 (C5) tren CUNG cac slide do (bo V2 theo yeu cau 17/11). Khoang 1-1,5 gio,
REM     phi OpenAI khoang 0,3-0,7 USD. Muon them V2 sau: sua --configs C0 C5 thanh C0 C5 C4 roi chay lai (tiep tuc).
REM   - Bi ngat (may ngu, tat Docker)? Nhap dup lai: phan da xong duoc giu (eval\v2\results\NLP).
REM   - Xong thi tu tinh lop A + E va lap bao cao tong hop. Log: eval\logs\nlp_log.txt
cd /d "%~dp0..\.."
if not exist eval\logs mkdir eval\logs
set LOG=eval\logs\nlp_log.txt
echo ==== BAT DAU %date% %time% ==== >> %LOG%
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )

echo [1/6] Build lai va khoi dong...
docker compose up -d --build >> %LOG% 2>&1
if errorlevel 1 goto :loi
timeout /t 30 /nobreak >nul

echo [2/6] Sinh cau V1 + V3 tren 9 chuong NLP (LAU NHAT: 1-1,5 gio). Theo doi: eval\logs\nlp_log.txt
docker compose exec -T api python -m eval.v2.run_ablation --docs-like Chuong --per-doc 12 --configs C0 C5 --skip-solver --resume eval/v2/results/NLP >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [3/6] Xuat du lieu cham diem...
docker compose exec -T api python -m eval.quality.export --results eval/v2/results/NLP --out eval/quality/data_nlp >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [4/6] Lop A + E cho V1, V3 va ablation nguon sinh (~10 phut)...
docker compose exec -T api python -m eval.quality.run_eval --data eval/quality/data_nlp --layers A E >> %LOG% 2>&1
if errorlevel 1 goto :loi

echo [5/6] Bao cao tong hop...
docker compose exec -T api python -m eval.tong_hop --data data_nlp >> %LOG% 2>&1

echo [6/6] Xuat file Excel toan bo cau hoi de kiem tra...
docker compose exec -T api sh -c "pip install -q openpyxl >/dev/null 2>&1"
docker compose exec -T api python -m eval.xuat_cau_hoi --data eval/quality/data_nlp --results eval/v2/results/NLP >> %LOG% 2>&1
echo.
echo XONG. File cau hoi: eval\v2\results\NLP\cau_hoi_nlp.xlsx  -  Bao cao: eval\BAO_CAO_DANH_GIA.md. Tiep theo: scripts\1_sinh_doi_chung_llm.bat
echo Quay lai Claude va bao "xong".
pause
exit /b 0
:loi
echo.
echo CO LOI - quay lai Claude va bao "loi" (log: %LOG%). Chay lai file nay se tiep tuc tu cho da xong.
pause
exit /b 1
