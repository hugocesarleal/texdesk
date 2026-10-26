# Avisos de terceiros

O TexDesk usa os componentes abaixo. Nenhum deles é modificado. A tabela diz como cada um chega ao usuário e qual licença se aplica.

| Componente | Uso no TexDesk | Como é obtido | Licença |
|---|---|---|---|
| [Feather Icons](https://github.com/feathericons/feather) | Desenhos dos ícones da interface (`static/common.js`) | Incluído no repositório (traçados SVG adaptados) | MIT |
| [CodeMirror 5](https://codemirror.net/5/) | Editor de código | Carregado de CDN (cdnjs) pelo navegador | MIT |
| [PDF.js](https://mozilla.github.io/pdf.js/) | Visualizador de PDF e miniaturas | Carregado de CDN (cdnjs) pelo navegador | Apache-2.0 |
| [Flask](https://flask.palletsprojects.com/) | Servidor web | Instalado via `pip` (`requirements.txt`) | BSD-3-Clause |
| [Tectonic](https://tectonic-typesetting.github.io/) | Motor de compilação LaTeX (XeTeX) | Baixado pelo `setup.ps1` para `tools/` | MIT |
| [Biber](https://github.com/plk/biber) | Processamento de bibliografia do `biblatex` | Baixado pelo `setup.ps1` para `tools/` | Artistic License 2.0 |
| [Pygments](https://pygments.org/) | Realce de código do pacote `minted` (opcional) | Instalado pelo usuário via `pip` | BSD-2-Clause |

Os pacotes LaTeX (classes, estilos, fontes) usados nas compilações são baixados pelo Tectonic sob demanda e seguem as licenças de cada pacote, em geral a LPPL.

Os binários do Tectonic e do Biber não fazem parte deste repositório: o `setup.ps1` baixa cada um do site oficial do respectivo projeto.

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
