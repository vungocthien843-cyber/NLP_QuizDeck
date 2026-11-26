@echo off
chcp 65001 >nul
REM Bao cao danh gia tong hop 3 tang (tu dong / nguoi cham / sinh vien) tu cac ket qua da co. Khong goi API.
REM Ket qua: eval\BAO_CAO_DANH_GIA.md. Chay lai moi khi co ket qua moi.
cd /d "%~dp0.."
docker info >nul 2>&1
if errorlevel 1 ( echo Docker Desktop chua chay. & pause & exit /b 1 )
docker compose up -d >nul 2>&1
docker compose exec -T api python -m eval.tong_hop
if errorlevel 1 ( echo CO LOI - chup man hinh gui Claude. & pause & exit /b 1 )
echo.
echo XONG: eval\BAO_CAO_DANH_GIA.md
pause
