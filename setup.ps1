# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

# Instala as dependências do TexDesk: Flask (Python) e o motor Tectonic.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Instalando dependências Python..."
# o instalador do Python deixa desmarcar o pip; o ensurepip (da biblioteca padrão) o repõe
python -c "import importlib.util, sys; sys.exit(importlib.util.find_spec('pip') is None)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "O pip não está instalado neste Python. Instalando..."
    python -m ensurepip --upgrade --default-pip
    if ($LASTEXITCODE -ne 0) { throw "Não foi possível instalar o pip. Reinstale o Python pelo python.org com a opção pip marcada." }
}
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Não foi possível instalar as dependências (veja o erro acima)." }

$exe = Join-Path $PSScriptRoot "tools\tectonic.exe"
if (-not (Test-Path $exe)) {
    Write-Host "Baixando Tectonic 0.15.0..."
    New-Item -ItemType Directory -Force tools | Out-Null
    $zip = Join-Path $env:TEMP "tectonic.zip"
    Invoke-WebRequest "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-x86_64-pc-windows-msvc.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath tools -Force
    Remove-Item $zip
}
& $exe --version

# biber 2.17 casa com o biblatex 3.17 do pacote padrão do Tectonic
$biber = Join-Path $PSScriptRoot "tools\biber.exe"
if (-not (Test-Path $biber)) {
    Write-Host "Baixando biber 2.17 (para biblatex)..."
    $zip = Join-Path $env:TEMP "biber.zip"
    Invoke-WebRequest -UserAgent "Wget" "https://sourceforge.net/projects/biblatex-biber/files/biblatex-biber/2.17/binaries/Windows/biber-MSWIN64.zip/download" -OutFile $zip
    Expand-Archive $zip -DestinationPath tools -Force
    Remove-Item $zip
}
& $biber --version

# Dicionários do corretor ortográfico (português e inglês; os outros idiomas são baixados no primeiro uso)
Write-Host "Baixando os dicionários do corretor ortográfico..."
python -m texdesk.spell pt_BR en_US

# Compila os modelos uma vez para o Tectonic já baixar os pacotes LaTeX que eles usam.
# Os pacotes ficam no cache do Tectonic (compartilhado por todos os projetos), então o
# primeiro documento criado a partir de um modelo compila em segundos.
Write-Host "`nPreparando os pacotes LaTeX dos modelos (só na primeira vez; pode levar alguns minutos)..."
$env:PATH = (Join-Path $PSScriptRoot "tools") + ";" + $env:PATH  # para o Tectonic achar o biber
$work = Join-Path $env:TEMP ("texdesk-modelos-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
foreach ($tpl in Get-ChildItem (Join-Path $PSScriptRoot "templates") -Directory) {
    $dir = Join-Path $work $tpl.Name
    Copy-Item -Recurse $tpl.FullName $dir
    New-Item -ItemType Directory (Join-Path $dir "out") | Out-Null
    Write-Host ("  {0,-14}" -f $tpl.Name) -NoNewline
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -FilePath $exe -WorkingDirectory $dir -NoNewWindow -Wait -PassThru `
        -ArgumentList "--keep-logs", "--outdir", "out", "--chatter", "minimal", "main.tex" `
        -RedirectStandardOutput (Join-Path $dir "out\stdout.txt") -RedirectStandardError (Join-Path $dir "out\stderr.txt")
    if ($p.ExitCode -eq 0) {
        Write-Host ("pronto ({0:N0} s)" -f $sw.Elapsed.TotalSeconds) -ForegroundColor Green
    } else {
        # não impede a instalação: os pacotes que faltarem são baixados na primeira compilação
        Write-Host "não foi possível (sem internet?); os pacotes serão baixados na primeira compilação" -ForegroundColor Yellow
    }
}
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue

# marca a instalação como completa (o iniciar.bat roda este script enquanto o marcador não existir)
Set-Content -Path (Join-Path $PSScriptRoot "tools\.setup-ok") -Value (Get-Date -Format s)
Write-Host "`nPronto! Rode iniciar.bat para abrir o TexDesk."
