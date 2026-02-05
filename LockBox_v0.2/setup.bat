@echo off
cd /d "%~dp0"

echo [LockBox] Checking for Python...
python --version >nul 2>&1
if %errorlevel% EQU 0 goto :PYTHON_FOUND

:PYTHON_MISSING
echo [LockBox] Python not found. Downloading Python 3.11...
powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.5/python-3.11.5-amd64.exe' -OutFile 'python_installer.exe'"

echo [LockBox] Installing Python (Silent)...
start /wait python_installer.exe /passive InstallAllUsers=0 PrependPath=1 Include_test=0

del python_installer.exe
echo [LockBox] Python installed.
echo [IMPORTANT] Please CLOSE this window and run setup.bat again.
pause
exit

:PYTHON_FOUND
echo [LockBox] Python is installed. Proceeding...

REM Set current directory variable
set "IP=%~dp0"
if "%IP:~-1%"=="\" set "IP=%IP:~0,-1%"

REM Add to User Path via PowerShell
powershell -Command "$p=[Environment]::GetEnvironmentVariable('Path', 'User'); if($p -notlike '*%IP%*') { [Environment]::SetEnvironmentVariable('Path', $p + ';%IP%', 'User'); }"

python install.py
pause