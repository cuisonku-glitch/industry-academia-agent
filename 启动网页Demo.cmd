@echo off
setlocal

title Industry-Academia Agent Web Demo
cd /d "%~dp0"

set "PYTHON_EXE=%USERPROFILE%\miniconda3\envs\industry_agent\python.exe"
if not defined DEMO_PORT set "DEMO_PORT=8501"
set "DEMO_URL=http://127.0.0.1:%DEMO_PORT%"
set "PYTHONUTF8=1"
set "HF_HUB_OFFLINE=1"
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python was not found in the industry_agent environment:
    echo %PYTHON_EXE%
    echo.
    echo Confirm that Miniconda is installed under your user folder.
    pause
    exit /b 1
)

if not exist "app\app.py" (
    echo [ERROR] app\app.py was not found. Keep this launcher in the project root.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Streamlit is not installed in the industry_agent environment.
    echo Run: python -m pip install -r requirements.txt
    pause
    exit /b 1
)

powershell.exe -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing '%DEMO_URL%/_stcore/health' -TimeoutSec 1; if($r.Content -eq 'ok'){exit 0}else{exit 1} } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo The web demo is already running. Opening it now...
    if /I not "%~1"=="--no-browser" start "" "%DEMO_URL%"
    exit /b 0
)

echo Starting the Industry-Academia Agent web demo...
echo The local model may need a few seconds to load the first time.
echo URL: %DEMO_URL%
echo Close this window or press Ctrl+C to stop the web server.
echo.

if /I not "%~1"=="--no-browser" start "" /B powershell.exe -NoProfile -WindowStyle Hidden -Command "$u='%DEMO_URL%'; for($i=0;$i -lt 60;$i++){ try { $r=Invoke-WebRequest -UseBasicParsing ($u+'/_stcore/health') -TimeoutSec 1; if($r.Content -eq 'ok'){ Start-Process $u; exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }"

"%PYTHON_EXE%" -m streamlit run "app\app.py" --server.address 127.0.0.1 --server.port %DEMO_PORT%

if errorlevel 1 (
    echo.
    echo [ERROR] The web server did not start. Keep this window open for diagnosis.
    pause
)
