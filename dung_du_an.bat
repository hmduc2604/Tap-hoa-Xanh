@echo off
rem Tap Hoa Xanh - dung toan bo du an (du lieu van duoc giu lai)
setlocal EnableExtensions
title Tap Hoa Xanh - Dung du an
cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
  echo Khong thay Docker. Neu ban dang chay che do local bang Python thi chi can dong cua so chay du an.
  echo.
  pause
  exit /b 0
)

echo Dang dung cac service...
docker compose down
echo.
echo Da dung. Du lieu van con. Muon xoa sach du lieu de bat dau lai tu dau, chay lenh: docker compose down -v
echo.
pause
exit /b 0
