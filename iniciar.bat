@echo off
rem TexDesk - https://github.com/hugocesarleal/texdesk
rem Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
rem SPDX-License-Identifier: MIT
title TexDesk
cd /d "%~dp0"
goto inicio
rem :depois fica no byte 317: o cmd continua dali se a atualizacao trocar o arquivo            
:depois
rem 3 = ja havia um servidor rodando: so abriu o navegador
if %errorlevel%==3 (
    timeout /t 5 >nul
    exit /b
)
echo.
echo  O servidor parou. Se apareceu algum erro acima, copie a mensagem.
pause
exit /b

:inicio
rem instala na primeira vez, e de novo se o ambiente Python (.venv) sumir ou quebrar
set "PY=.venv\Scripts\python.exe"
set PRONTO=1
if not exist tools\.setup-ok set PRONTO=0
if not exist "%PY%" set PRONTO=0
if %PRONTO%==1 (
    "%PY%" -c "" 2>nul || set PRONTO=0
)
if %PRONTO%==0 (
    powershell -ExecutionPolicy Bypass -File setup.ps1
    if errorlevel 1 (
        echo.
        echo  A instalacao nao terminou. Veja a mensagem acima.
        pause
        exit /b 1
    )
)

"%PY%" -m texdesk --abrir
goto depois
