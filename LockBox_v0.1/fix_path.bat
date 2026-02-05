@echo off
cd /d "%~dp0"
set "IP=%~dp0"
if "%IP:~-1%"=="\" set "IP=%IP:~0,-1%"
powershell -Command "$p=[Environment]::GetEnvironmentVariable('Path', 'User'); if($p -notlike '*%IP%*') { [Environment]::SetEnvironmentVariable('Path', $p + ';%IP%', 'User'); }"
