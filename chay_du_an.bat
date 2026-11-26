@echo off
rem ====================================================================
rem  Tap Hoa Xanh - bam dup 1 lan de chay toan bo du an
rem  Uu tien Docker Compose, day du PostgreSQL va RabbitMQ. Neu may chua
rem  cai Docker thi tu chuyen sang che do local bang Python.
rem  Luu y: file nay viet khong dau va xuong dong kieu Windows, CRLF.
rem ====================================================================
setlocal EnableExtensions EnableDelayedExpansion
title Tap Hoa Xanh - Chay du an
cd /d "%~dp0"

echo ==============================================
echo   TAP HOA XANH - khoi dong toan bo du an
echo ==============================================
echo.

rem ---------- 1. Docker
where docker >nul 2>&1
if errorlevel 1 goto :no_docker

docker info >nul 2>&1
if not errorlevel 1 goto :docker_ready

echo [1/4] Docker Desktop chua chay, dang mo Docker Desktop...
set "DOCKER_EXE="
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" set "DOCKER_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
if not defined DOCKER_EXE if exist "%LocalAppData%\Programs\Docker\Docker\Docker Desktop.exe" set "DOCKER_EXE=%LocalAppData%\Programs\Docker\Docker\Docker Desktop.exe"
if not defined DOCKER_EXE (
  echo [LOI] Khong tim thay Docker Desktop. Hay mo no bang tay roi chay lai file nay.
  goto :fail
)
start "" "%DOCKER_EXE%"
set /a WAITED=0

:wait_docker
docker info >nul 2>&1
if not errorlevel 1 goto :docker_ready
if !WAITED! GEQ 300 (
  echo [LOI] Docker Desktop chua san sang sau 5 phut. Hay kiem tra Docker Desktop roi chay lai.
  goto :fail
)
timeout /t 5 /nobreak >nul
set /a WAITED+=5
echo       dang cho Docker Desktop, da !WAITED! giay
goto :wait_docker

:docker_ready
echo [1/4] Docker da san sang.

rem ---------- 2. File .env, cau hinh va khoa AI neu co. Khong in noi dung ra man hinh
if exist ".env" goto :env_ok
if exist ".env.example" copy /y ".env.example" ".env" >nul
echo [2/4] Chua co file .env, da tao tu .env.example voi cau hinh mac dinh.
:env_ok

set "WEB_PORT=8080"
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"WEB_PORT=" ".env"`) do set "WEB_PORT=%%b"
)
for /f "tokens=1" %%p in ("!WEB_PORT!") do set "WEB_PORT=%%p"
if not defined WEB_PORT set "WEB_PORT=8080"

rem ---------- 3. Build va chay cac service
set "COMPOSE=docker compose"
docker compose version >nul 2>&1
if errorlevel 1 (
  where docker-compose >nul 2>&1
  if errorlevel 1 (
    echo [LOI] Khong tim thay lenh docker compose. Hay cap nhat Docker Desktop.
    goto :fail
  )
  set "COMPOSE=docker-compose"
)

echo [3/4] Dang build va khoi dong cac service. Lan dau co the mat vai phut...
echo.
%COMPOSE% up -d --build
if errorlevel 1 (
  echo.
  echo [LOI] Khong khoi dong duoc. Neu cong 8080, 8000, 5433 hoac 15672 bi trung thi doi WEB_PORT, GATEWAY_PORT, POSTGRES_PORT, RABBITMQ_UI_PORT trong file .env.
  echo       Xem log bang lenh: %COMPOSE% logs --tail 50
  goto :fail
)

rem ---------- 4. Cho he thong san sang roi mo trinh duyet
echo.
echo [4/4] Dang cho he thong san sang...
where curl >nul 2>&1
if errorlevel 1 (
  timeout /t 45 /nobreak >nul
  goto :open_browser
)
set /a TRIES=0

:wait_web
set "CODE=000"
for /f %%c in ('curl.exe -s -o NUL -w "%%{http_code}" --max-time 5 "http://localhost:!WEB_PORT!/api/health" 2^>NUL') do set "CODE=%%c"
if "!CODE!"=="200" goto :open_browser
rem Ma 207 nghia la con service dang khoi dong. Sau khoang 90 giay thi cho qua
if "!CODE!"=="207" if !TRIES! GEQ 18 goto :open_browser
set /a TRIES+=1
if !TRIES! GEQ 60 (
  echo [CANH BAO] Sau 5 phut he thong van chua bao day du, van mo trinh duyet. Co the mot vai service dang khoi dong them.
  goto :open_browser
)
timeout /t 5 /nobreak >nul
goto :wait_web

:open_browser
echo.
echo ==============================================
echo   DU AN DANG CHAY
echo ==============================================
echo   Cua hang : http://localhost:!WEB_PORT!
echo   Quan tri : http://localhost:!WEB_PORT!/admin/
echo   Hop dong : http://localhost:!WEB_PORT!/api-docs.html
echo   Tai khoan quan tri dung thu: admin@taphoa.vn / Admin@123
echo.
start "" "http://localhost:!WEB_PORT!"
echo De dung du an, chay file dung_du_an.bat
echo Cua so nay co the dong, du an van chay nen.
echo.
pause
exit /b 0

rem ---------- Du phong khi khong co Docker: chay local bang Python, dung SQLite
:no_docker
echo [CHU Y] Khong tim thay Docker. Chuyen sang che do local bang Python, khong can Docker.
set "PY="
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if not defined PY (
  py -3 --version >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  echo [LOI] Can cai Docker Desktop hoac Python 3.10 tro len de chay du an.
  goto :fail
)
echo Dang cai thu vien Python...
%PY% -m pip install -q -r requirements-local.txt
if errorlevel 1 (
  echo [LOI] Cai thu vien Python that bai.
  goto :fail
)
start "" /min powershell -NoProfile -Command "Start-Sleep -Seconds 15; Start-Process 'http://localhost:8000'"
echo.
echo   Cua hang : http://localhost:8000
echo   Quan tri : http://localhost:8000/admin/
echo   DONG CUA SO NAY de dung du an.
echo.
%PY% run_local.py
pause
exit /b 0

:fail
echo.
pause
exit /b 1
