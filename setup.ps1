# TexDesk — https://github.com/hugocesarleal/texdesk
# Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
# SPDX-License-Identifier: MIT

# Instala o TexDesk no Windows: ambiente Python (.venv), Tectonic, biber
# e os pacotes LaTeX dos modelos. É o equivalente do setup.sh (Linux e macOS).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# ---- Python 3.10+ num ambiente isolado (.venv): as dependências do TexDesk não se
#      misturam com as de outros programas no Python do sistema
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python não encontrado. Instale o Python 3.10 ou mais novo pelo python.org, marcando 'Add Python to PATH'."
}
python -c "import sys; sys.exit(sys.version_info < (3, 10))"
if ($LASTEXITCODE -ne 0) { throw "É preciso o Python 3.10 ou mais novo (encontrado: $(python --version 2>&1))." }
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $py) {
    # o .venv quebra se o Python que o criou for desinstalado ou trocado de versão
    # (try: com $ErrorActionPreference = "Stop", um python.exe que nem abre lança exceção)
    $ok = $false
    try { & $py -c "pass" 2>$null; $ok = ($LASTEXITCODE -eq 0) } catch { }
    if (-not $ok) {
        Write-Host "O ambiente Python (.venv) não funciona mais. Criando de novo..."
        Remove-Item -Recurse -Force (Join-Path $PSScriptRoot ".venv")
    }
}
if (-not (Test-Path $py)) {
    Write-Host "Criando o ambiente Python (.venv)..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Não foi possível criar o .venv (veja o erro acima). Reinstale o Python pelo python.org." }
}
Write-Host "Instalando dependências Python..."
& $py -m pip install --quiet --disable-pip-version-check -r requirements.txt
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
& $py -m texdesk.spell pt_BR en_US

# Modelos do IFMG: a versão mais recente, direto do repositório do autor (Marcos Roberto Ribeiro).
# Sem internet, não impede a instalação: o TexDesk tenta de novo quando for aberto.
Write-Host "Baixando os modelos do IFMG..."
& $py -m texdesk.external_templates

# Compila os modelos uma vez para o Tectonic já baixar os pacotes LaTeX que eles usam.
# Os pacotes ficam no cache do Tectonic (compartilhado por todos os projetos), então o
# primeiro documento criado a partir de um modelo compila em segundos.
Write-Host "`nPreparando os pacotes LaTeX dos modelos (só na primeira vez; pode levar alguns minutos)..."
$env:PATH = (Join-Path $PSScriptRoot "tools") + ";" + $env:PATH  # para o Tectonic achar o biber
$work = Join-Path $env:TEMP ("texdesk-modelos-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$modelos = @(Get-ChildItem (Join-Path $PSScriptRoot "templates") -Directory)
$baixados = Join-Path $PSScriptRoot "tools\templates"
if (Test-Path $baixados) { $modelos += Get-ChildItem $baixados -Directory | Where-Object { -not $_.Name.StartsWith(".") } }
foreach ($tpl in $modelos) {
    $dir = Join-Path $work $tpl.Name
    Copy-Item -Recurse $tpl.FullName $dir
    New-Item -ItemType Directory (Join-Path $dir "out") | Out-Null
    # \include{capitulos/x} grava out\capitulos\x.aux, e o Tectonic não cria a pasta sozinho
    # (o compilador do TexDesk faz o mesmo antes de cada compilação)
    foreach ($sub in Get-ChildItem $dir -Directory -Recurse) {
        $rel = $sub.FullName.Substring($dir.Length + 1)
        if ($rel -ne "out" -and -not $rel.StartsWith("out\")) {
            New-Item -ItemType Directory -Force (Join-Path $dir "out\$rel") | Out-Null
        }
    }
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
exit 0  # um download que falhou acima (modelos do IFMG sem internet) não é falha da instalação
