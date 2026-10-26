@echo off
title TexDesk
cd /d "%~dp0"
if not exist tools\tectonic.exe powershell -ExecutionPolicy Bypass -File setup.ps1

python server.py --abrir

rem 3 = ja havia um servidor rodando: so abriu o navegador
if %errorlevel%==3 (
    timeout /t 5 >nul
    exit /b
)
echo.
echo  O servidor parou. Se apareceu algum erro acima, copie a mensagem.
pause
