# Avisos de terceiros

O TexDesk usa os componentes abaixo. Nenhum deles é modificado. A tabela diz como cada um chega ao usuário e qual licença se aplica. As bibliotecas da interface vêm junto com o projeto, então o editor funciona sem internet.

| Componente | Uso no TexDesk | Como é obtido | Licença |
|---|---|---|---|
| [Feather Icons](https://github.com/feathericons/feather) | Desenhos dos ícones da interface (`static/common.js`) | Incluído no repositório (traçados SVG adaptados) | MIT |
| [CodeMirror](https://codemirror.net/5/) 5.65.16 | Editor de código | Incluído no repositório em `static/vendor/codemirror-5.65.16/`, sem modificações (licença no `LICENSE` da pasta) | MIT |
| [PDF.js](https://mozilla.github.io/pdf.js/) 3.11.174 | Visualizador de PDF e miniaturas | Incluído no repositório em `static/vendor/pdfjs-3.11.174/`, sem modificações (licença no `LICENSE` da pasta) | Apache-2.0 |
| [Flask](https://flask.palletsprojects.com/) | Servidor web | Instalado via `pip` (`requirements.txt`) | BSD-3-Clause |
| [waitress](https://github.com/Pylons/waitress) | Servidor HTTP que serve o Flask | Instalado via `pip` (`requirements.txt`) | ZPL-2.1 |
| [keyring](https://github.com/jaraco/keyring) | Guarda o token do Google Drive no cofre de senhas do sistema | Instalado via `pip` (`requirements.txt`) | MIT |
| [Spylls](https://github.com/zverok/spylls) | Corretor ortográfico (lê os dicionários Hunspell) | Instalado via `pip` (`requirements.txt`) | MPL-2.0 |
| [Dicionários do LibreOffice](https://github.com/LibreOffice/dictionaries) (VERO pt_BR, pt_PT, SCOWL en_US/en_GB, es_ES, fr, it_IT, de_DE) | Dicionários do corretor ortográfico | Baixados para `tools/dictionaries/` (português do Brasil e inglês dos EUA na instalação; os outros no primeiro uso) | Licença de cada dicionário, no repositório do LibreOffice (pt_BR: LGPL-3.0/MPL-2.0; en_US: licença do SCOWL, permissiva) |
| [Tectonic](https://tectonic-typesetting.github.io/) | Motor de compilação LaTeX (XeTeX) | Baixado pelo `setup.ps1` para `tools/` | MIT |
| [Biber](https://github.com/plk/biber) | Processamento de bibliografia do `biblatex` | Baixado pelo `setup.ps1` para `tools/` | Artistic License 2.0 |
| [Pygments](https://pygments.org/) | Realce de código do pacote `minted` (opcional) | Instalado pelo usuário via `pip` | BSD-2-Clause |
| [IFTeX2024](https://github.com/ribeiromarcos/iftex2024) (`iftex2024.cls`, `biblatexfix.sty`), por Marcos Roberto Ribeiro (IFMG) | Modelo "Artigo IFMG" (`templates/ifmg-artigo/`) | Incluído no repositório, sem modificações | GPL-3.0 |
| [IFSlides2024](https://github.com/ribeiromarcos/ifslides2024) (`ifslides2024.sty`, `biblatexfix.sty`), por Marcos Roberto Ribeiro (IFMG) | Modelo "Slides IFMG" (`templates/ifmg-slides/`) | Incluído no repositório, sem modificações | GPL-3.0 |

| [abnTeX2](https://www.abntex.net.br/) | Classe e estilos do modelo "Trabalho acadêmico ABNT" (`templates/abnt/`) | Baixado pelo Tectonic na compilação (não fica no repositório). O documento inicial do modelo foi escrito para o TexDesk, seguindo a estrutura do modelo canônico do abnTeX2 | LPPL-1.3c |

Os pacotes LaTeX (classes, estilos, fontes) usados nas compilações são baixados pelo Tectonic sob demanda e seguem as licenças de cada pacote, em geral a LPPL.

Os binários do Tectonic e do Biber não fazem parte deste repositório: o `setup.ps1` baixa cada um do site oficial do respectivo projeto.

### Modelos do IFMG (GPL-3.0)

Os arquivos de classe e estilo dos modelos "Artigo IFMG" e "Slides IFMG" são obra de Marcos Roberto Ribeiro (IFMG) e continuam sob a GNU General Public License v3. Os originais, a documentação e as versões mais recentes estão nos repositórios do autor:

- IFTeX2024 (trabalhos acadêmicos): https://github.com/ribeiromarcos/iftex2024
- IFSlides2024 (apresentações): https://github.com/ribeiromarcos/ifslides2024

 O texto completo da licença acompanha cada modelo, no arquivo `LICENSE` da pasta. Eles são distribuídos junto com o TexDesk como obras separadas: a licença MIT do TexDesk não se aplica a eles, e a GPL deles não se aplica ao restante do TexDesk.

- `templates/ifmg-artigo/main.tex` é o exemplo de artigo original do pacote IFTeX2024 (`exemplo_artigo.tex`), e `referencias.bib` é o arquivo de referências de exemplo do mesmo pacote.
- `templates/ifmg-slides/main.tex` é um documento inicial escrito para o TexDesk, que usa o tema IFSlides2024.

Os projetos que você criar a partir desses modelos são seus. A GPL só se aplica se você redistribuir os próprios arquivos `.cls`/`.sty`.

---

## Feather Icons — licença MIT

Os ícones em `static/common.js` foram adaptados do Feather Icons.

```
The MIT License (MIT)

Copyright (c) 2013-2023 Cole Bemis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
