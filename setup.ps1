# Instala as dependências do TexDesk: Flask (Python) e o motor Tectonic.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Instalando dependências Python..."
python -m pip install -r requirements.txt

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
Write-Host "`nPronto! Rode iniciar.bat para abrir o TexDesk."
