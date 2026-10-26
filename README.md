<p align="center"><img src="static/logo.svg" alt="" width="96" height="96"></p>

<h1 align="center">TexDesk</h1>

<p align="center">Editor e compilador LaTeX que roda no seu computador, com interface no navegador.</p>

<p align="center"><a href="https://github.com/hugocesarleal/texdesk">github.com/hugocesarleal/texdesk</a></p>

<p align="center">
  <a href="https://github.com/hugocesarleal/texdesk/actions/workflows/tests.yml"><img src="https://github.com/hugocesarleal/texdesk/actions/workflows/tests.yml/badge.svg" alt="Testes"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licen%C3%A7a-MIT-green" alt="Licença MIT"></a>
</p>

## Como usar

1. Baixe o código (`git clone https://github.com/hugocesarleal/texdesk.git`, ou **Code → Download ZIP** no GitHub). É preciso ter o [Python 3.10 ou mais novo](https://www.python.org/downloads/) instalado.
2. Dê dois cliques em `iniciar.bat` (na primeira vez ele instala o Flask e baixa o Tectonic e o Biber).
3. O navegador abre em http://127.0.0.1:5050.
4. Crie um projeto e escreva. Use **Ctrl+S** ou **Ctrl+Enter** para compilar.

Na instalação, o `setup.ps1` compila os três modelos uma vez para já baixar os pacotes LaTeX que eles usam (cerca de 20 MB, 1 a 2 minutos). Os pacotes ficam num cache do Tectonic compartilhado por todos os projetos, em `%LOCALAPPDATA%\TectonicProject`. Um documento que use um pacote novo baixa só esse pacote, na primeira compilação.

## Recursos

| Área | O que faz |
|---|---|
| Painel de projetos | Criar (em branco, [Slides IFMG](https://github.com/ribeiromarcos/ifslides2024) ou [Artigo IFMG](https://github.com/ribeiromarcos/iftex2024)), renomear, duplicar, excluir, baixar/enviar `.zip`, miniatura da 1ª página |
| Árvore de arquivos | Pastas, upload (botão ou arrastar e soltar), renomear/mover, definir documento principal |
| Editor | CodeMirror com realce LaTeX, autocompletar (`\comandos`, ambientes, `\ref`, `\cite`, pacotes), busca, Ctrl+/ comenta, Ctrl+B/Ctrl+I, salvamento automático |
| Compilador | Tectonic (XeTeX + BibTeX/biber automáticos, reexecuta até estabilizar as referências), gera o PDF mesmo com erros, shell-escape opcional |
| Logs | Erros, avisos e caixas overfull/underfull com arquivo e linha. Clique para ir ao código. Marcadores no editor e log bruto |
| PDF | Visualizador PDF.js com zoom, ajuste à largura e recompilação sem piscar |
| SyncTeX | Clique duplo no PDF vai ao código; o botão → vai do código ao PDF |
| Google Drive | Sincronização opcional dos projetos, a cada 5 s durante a edição |
| Outros | Estrutura do documento (seções), compilação automática, tema claro/escuro, layout móvel |

## Google Drive

No painel de projetos, clique em **Google Drive**:

1. Na primeira vez, siga o passo a passo para criar um cliente OAuth ("App para computador") no Google Cloud e envie o JSON. É gratuito e só precisa ser feito uma vez.
2. Clique em **Conectar** e faça login com a sua conta Google.
3. Ligue **Sincronizar todos os projetos**, ou ligue projeto por projeto em Configurações, no editor.

Como funciona:
- Os projetos ficam em `TexDesk/<projeto>` no seu Drive.
- Durante a edição, as alterações são enviadas a cada 5 s, e só os arquivos que mudaram.
- Arquivos apagados aqui vão para a lixeira do Drive. Excluir um projeto aqui não o apaga do Drive.
- O app só pede o escopo `drive.file`, então enxerga apenas os arquivos que ele mesmo criou.
- Em outro computador, use as mesmas credenciais e clique em **Baixar** na lista "Projetos no Drive".
- O token de acesso fica em `.drive/`. Não compartilhe essa pasta.
- A sincronização vai do computador para o Drive. Editar o mesmo projeto em dois computadores ao mesmo tempo não é mesclado: vale a última versão enviada.

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests
```

Os testes usam uma pasta de dados temporária e um Google Drive falso, então não tocam nos seus projetos nem na sua conta. Os de compilação rodam só se o Tectonic estiver em `tools/`. O GitHub Actions roda tudo a cada push, no Windows e no Linux.

## Estrutura

```
server.py      servidor web: API de projetos/arquivos e compilação
latexlog.py    leitor do log do TeX (erros, avisos e caixas, com arquivo e linha)
synctex.py     busca direta/inversa no .synctex.gz
drive_sync.py  sincronização com o Google Drive (OAuth, envio incremental, restauração)
static/        interface (HTML/CSS/JS); static/vendor/ tem o CodeMirror e o PDF.js
tests/         testes automáticos (pytest) e fixtures
templates/     modelos de projeto
projects/      seus projetos (um diretório por projeto)
output/        PDFs e arquivos de compilação
tools/         tectonic.exe e biber.exe (baixados pelo setup.ps1)
```

## Observações

- O motor é XeTeX (via Tectonic): `fontspec` funciona e `inputenc` é aceito. Projetos que exigem `pdflatex` especificamente costumam compilar sem mudanças.
- `biblatex` usa o `biber` 2.17 em `tools/` (o `setup.ps1` baixa), que casa com o biblatex 3.17 do pacote do Tectonic.
- `minted` precisa de shell-escape (ligue nas opções de compilação do projeto) e do Pygments (`pip install pygments`).
- EPS não é suportado sem Ghostscript; converta as figuras para PDF ou PNG.
- Depois da instalação, funciona sem internet: o editor e o visualizador de PDF vêm junto com o projeto (`static/vendor/`). A internet só é necessária para baixar pacotes LaTeX que ainda não estão no cache e para o Google Drive.
- Ele roda só em `127.0.0.1` e é feito para uso local, por uma pessoa.

## Licença

Copyright (c) 2026 [Hugo César Leal](https://github.com/hugocesarleal). Código-fonte: [github.com/hugocesarleal/texdesk](https://github.com/hugocesarleal/texdesk).

O TexDesk é distribuído sob a [licença MIT](LICENSE). As licenças das ferramentas e bibliotecas de terceiros usadas pelo projeto estão em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
