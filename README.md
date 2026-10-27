<p align="center"><img src="static/logo.svg" alt="" width="96" height="96"></p>

<h1 align="center">TexDesk</h1>

<p align="center">Editor e compilador LaTeX que roda no seu computador, com interface no navegador.</p>

<p align="center"><a href="https://github.com/hugocesarleal/texdesk">github.com/hugocesarleal/texdesk</a></p>

<p align="center">
  <a href="https://github.com/hugocesarleal/texdesk/actions/workflows/tests.yml"><img src="https://github.com/hugocesarleal/texdesk/actions/workflows/tests.yml/badge.svg" alt="Testes"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licen%C3%A7a-MIT-green" alt="Licença MIT"></a>
</p>

## Instalação

Em todos os sistemas é preciso ter o [Python 3.10 ou mais novo](https://www.python.org/downloads/).

Baixe o pacote do seu sistema na [página de releases](https://github.com/hugocesarleal/texdesk/releases/latest). Eles já trazem o motor LaTeX (Tectonic) e o biber:

| Sistema | Arquivo | Como abrir |
|---|---|---|
| Windows 10/11 (64 bits) | `texdesk-…-windows-x64.zip` | Extraia e dê dois cliques em `iniciar.bat` |
| Linux (Intel/AMD 64 bits) | `texdesk-…-linux-x64.tar.gz` | Extraia e rode `./iniciar.sh` |
| Linux (ARM 64 bits) | `texdesk-…-linux-arm64.tar.gz` | Extraia e rode `./iniciar.sh` |
| macOS (Apple Silicon: M1, M2, M3…) | `texdesk-…-macos-arm64.tar.gz` | Extraia e rode `./iniciar.sh` no Terminal |
| macOS (Intel) | `texdesk-…-macos-x64.tar.gz` | Extraia e rode `./iniciar.sh` no Terminal |

O navegador abre em http://127.0.0.1:5050. Crie um projeto e escreva; use **Ctrl+S** ou **Ctrl+Enter** para compilar.

Também dá para usar direto do código (`git clone https://github.com/hugocesarleal/texdesk.git`). Nesse caso, na primeira vez o `iniciar.bat`/`iniciar.sh` baixa o Tectonic e o biber do site de cada projeto.

Na primeira vez, a instalação (`setup.ps1` no Windows, `setup.sh` no Linux e no macOS) compila os três modelos para já baixar os pacotes LaTeX que eles usam (cerca de 20 MB, 1 a 2 minutos). Os pacotes ficam num cache do Tectonic compartilhado por todos os projetos. Um documento que use um pacote novo baixa só esse pacote, na primeira compilação.

No Linux e no macOS, as dependências Python ficam num ambiente isolado (`.venv/`, dentro da pasta do TexDesk). No Debian/Ubuntu pode ser preciso instalar o `python3-venv` antes (`sudo apt install python3-venv`).

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

## Releases

Para publicar uma versão, crie uma tag (`git tag v0.1.0 && git push origin v0.1.0`). O GitHub Actions monta um pacote para cada sistema, já com o Tectonic e o biber, instala e testa cada um no próprio sistema, e só então cria a release com os arquivos.

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests
```

Os testes usam uma pasta de dados temporária e um Google Drive falso, então não tocam nos seus projetos nem na sua conta. Os de compilação rodam só se o Tectonic estiver em `tools/`. O GitHub Actions roda a instalação completa e os testes a cada push, no Windows, no Linux e no macOS.

## Estrutura

```
texdesk/               servidor (python -m texdesk)
  __main__.py          inicialização: confere se já há um TexDesk rodando e abre o navegador
  app.py               create_app(): monta o Flask com segurança, rotas e erros
  config.py            caminhos e constantes
  security.py          proteções contra CSRF e DNS rebinding
  storage.py           projetos no disco: caminhos seguros, configurações, árvore
  compiler.py          chamada ao Tectonic e leitura dos resultados
  latexlog.py          leitor do log do TeX (erros, avisos e caixas, com arquivo e linha)
  synctex.py           busca direta/inversa no .synctex.gz
  drive_sync.py        sincronização com o Google Drive (OAuth, envio incremental, restauração)
  services.py          conexão com o Drive e processo de sincronização
  routes/              rotas HTTP: pages, projects, files, compile, drive
static/                interface
  index.html, editor.html
  css/                 base.css (cores e componentes), dashboard.css, editor.css
  js/common.js         API, ícones, modais e miniaturas
  js/dashboard/        painel de projetos: projects, new-project, drive-panel, drive-import, main
  js/editor/           editor: core, files, compile, pdf, layout, main, completions
  vendor/              CodeMirror e PDF.js
tests/                 testes automáticos (pytest) e fixtures
templates/     modelos de projeto
projects/      seus projetos (um diretório por projeto)
output/        PDFs e arquivos de compilação
tools/         Tectonic e biber (vêm nos pacotes de release ou são baixados na instalação)
scripts/       empacotamento das releases (usado pelo GitHub Actions)
```

## Observações

- O motor é XeTeX (via Tectonic): `fontspec` funciona e `inputenc` é aceito. Projetos que exigem `pdflatex` especificamente costumam compilar sem mudanças.
- `biblatex` usa o `biber` 2.17 em `tools/`, que casa com o biblatex 3.17 do pacote do Tectonic. O biber 2.17 não tem versão para Linux ARM64; nesse sistema, projetos com `biblatex` precisam do biber do sistema (`sudo apt install biber`).
- `minted` precisa de shell-escape (ligue nas opções de compilação do projeto) e do Pygments (`pip install pygments`).
- EPS não é suportado sem Ghostscript; converta as figuras para PDF ou PNG.
- Depois da instalação, funciona sem internet: o editor e o visualizador de PDF vêm junto com o projeto (`static/vendor/`). A internet só é necessária para baixar pacotes LaTeX que ainda não estão no cache e para o Google Drive.
- Ele roda só em `127.0.0.1` e é feito para uso local, por uma pessoa.

## Licença

Copyright (c) 2026 [Hugo César Leal](https://github.com/hugocesarleal). Código-fonte: [github.com/hugocesarleal/texdesk](https://github.com/hugocesarleal/texdesk).

O TexDesk é distribuído sob a [licença MIT](LICENSE). As licenças das ferramentas e bibliotecas de terceiros usadas pelo projeto estão em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
