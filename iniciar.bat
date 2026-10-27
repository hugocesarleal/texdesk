@echo off
rem TexDesk - https://github.com/hugocesarleal/texdesk
rem Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
rem SPDX-License-Identifier: MIT
title TexDesk
cd /d "%~dp0"
if not exist tools\.setup-ok powershell -ExecutionPolicy Bypass -File setup.ps1

python -m texdesk --abrir

rem 3 = ja havia um servidor rodando: so abriu o navegador
if %errorlevel%==3 (
    timeout /t 5 >nul
    exit /b
)
echo.
echo  O servidor parou. Se apareceu algum erro acima, copie a mensagem.
pause
