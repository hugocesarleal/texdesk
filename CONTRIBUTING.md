# Como contribuir com o TexDesk

Obrigado pelo interesse! Correções, melhorias, novos modelos e relatos de problemas são bem-vindos.

## Antes de começar

- **Encontrou um problema ou tem uma ideia?** Abra uma [issue](https://github.com/hugocesarleal/texdesk/issues/new/choose). Os modelos pedem as informações que ajudam a resolver mais rápido.
- **Achou uma falha de segurança?** Não abra uma issue pública. Veja o [SECURITY.md](SECURITY.md).
- **Mudanças grandes** (um recurso novo, mudar o funcionamento de algo existente): abra uma issue antes, para conversarmos sobre a abordagem.
- O projeto é em **português**: código, comentários, interface, issues e pull requests.

## Preparando o ambiente

É preciso ter o [Python 3.10 ou mais novo](https://www.python.org/downloads/) e o git.

```bash
git clone https://github.com/hugocesarleal/texdesk.git
cd texdesk
```

Rode a instalação uma vez. Ela baixa o Tectonic e o biber para a pasta `tools/` e prepara os pacotes LaTeX dos modelos:

- **Windows:** `powershell -ExecutionPolicy Bypass -File setup.ps1`
- **Linux e macOS:** `./setup.sh` (cria o ambiente Python em `.venv/`)

Depois instale as ferramentas de desenvolvimento (testes e linter):

```bash
python -m pip install -r requirements-dev.txt          # Windows
.venv/bin/python -m pip install -r requirements-dev.txt  # Linux e macOS
```

Para abrir o TexDesk: `python -m texdesk --abrir` (ou `iniciar.bat` / `./iniciar.sh`).

## Organização do código

A seção [Estrutura do README](README.md#estrutura) descreve cada pasta e módulo. Resumo:

- `texdesk/`: o servidor (Flask). As rotas ficam em `texdesk/routes/`, uma área por arquivo.
- `static/`: a interface (HTML, CSS e JavaScript, sem etapa de build). O JavaScript fica em `static/js/dashboard/` (painel de projetos) e `static/js/editor/` (editor).
- `templates/`: os modelos de projeto. Cada um tem um `.template.json` com nome e descrição.
- `tests/`: os testes automáticos.

## Antes de enviar

Rode os testes e o linter. São os mesmos que o GitHub Actions roda em cada pull request:

```bash
python -m pytest              # testes
ruff check .                  # linter
ruff format .                 # formata o código no padrão do projeto
```

- Os testes usam uma pasta de dados temporária e um Google Drive falso: não mexem nos seus projetos nem na sua conta.
- **Corrigiu um bug?** Acrescente um teste que falhava antes da correção.
- **Mudou algo visível na interface?** Descreva no pull request e, se puder, inclua uma captura de tela.
- **Mudou o comportamento?** Registre na seção "Não lançado" do [CHANGELOG.md](CHANGELOG.md).
- **Arquivos novos de código** começam com o cabeçalho de licença usado nos outros arquivos (`SPDX-License-Identifier: MIT`).

## Pull requests

1. Faça um fork e crie um branch a partir do `main` (ex.: `corrige-log-de-erros`).
2. Mantenha cada pull request focado em um assunto.
3. Escreva mensagens de commit que digam o que mudou e por quê.
4. Abra o pull request preenchendo o modelo. O CI precisa passar no Windows, no Linux e no macOS.

## Licença

Ao contribuir, você concorda que sua contribuição seja distribuída sob a [licença MIT](LICENSE) do projeto. Os arquivos dos modelos do IFMG (`templates/ifmg-*`) são de outro autor e seguem a GPL-3.0; mudanças neles devem ir para os [repositórios originais](THIRD_PARTY_NOTICES.md#modelos-do-ifmg-gpl-30).
