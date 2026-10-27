# Histórico de mudanças

As mudanças relevantes de cada versão ficam registradas aqui. O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), e as versões seguem o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

## [0.4.0] - 2026-10-27

### Adicionado
- Com mais de um documento no projeto, o TexDesk compila o que está aberto no editor. Um capítulo incluído por outro arquivo compila o documento que o inclui. Dá para desligar no menu do botão Compilar ou nas Configurações.

## [0.3.1] - 2026-10-27

### Corrigido
- O TexDesk não abria num Python instalado sem o pip ("No module named pip"). Agora o pip é instalado sozinho com o `ensurepip`, e, se isso falhar, aparece uma mensagem explicando o que fazer.
- O `setup.ps1` marcava a instalação como concluída mesmo quando a instalação das dependências falhava. Agora ele para e tenta de novo na próxima abertura.

## [0.3.0] - 2026-10-27

Abas, lixeira, dicas nos erros, referências pelo DOI, modelo ABNT e um painel de projetos mais organizado.

### Adicionado
- Abas com os arquivos abertos no editor. Um ponto na aba indica alteração ainda não salva, e o clique do meio fecha a aba.
- Lixeira de projetos: um projeto excluído fica 30 dias nela, com o histórico de versões, e pode ser restaurado.
- Detecção de mudanças feitas fora do editor: se um arquivo aberto mudar no disco, o TexDesk recarrega o arquivo ou, se houver alterações não salvas, pergunta qual versão manter. A versão que fica de fora vai para o histórico.
- Buscar e substituir no arquivo (Ctrl+H) e em todos os arquivos do projeto, com o projeto guardado no histórico antes da substituição.
- Dicas em português para os erros de compilação mais comuns, com um botão que adiciona ao preâmbulo o pacote que falta.
- Referências pelo DOI: o botão **Referência** busca a referência em BibTeX no doi.org, acrescenta ao `.bib` e insere o `\cite` no texto.
- Colar (Ctrl+V) ou arrastar uma imagem para o código salva a imagem na pasta de figuras e insere a figura com legenda e rótulo.
- Texto selecionável no PDF, para copiar trechos.
- Modo apresentação em tela cheia, para slides, e opção de PDF com fundo escuro.
- Modelo "Trabalho acadêmico ABNT", com a classe abnTeX2: capa, folha de rosto, resumos, listas, sumário, capítulos e referências no padrão autor-data.
- Painel de projetos: ordem por data ou nome, etiquetas para filtrar e projetos fixados no topo.
- Aviso de versão nova no painel (consulta as releases do GitHub uma vez por dia; `TEXDESK_UPDATE_CHECK=0` desliga).
- O TexDesk pode ser instalado como aplicativo no Chrome e no Edge, numa janela própria.
- Janela com todos os atalhos de teclado (F1).

### Alterado
- As configurações do editor estão separadas em "Este projeto" e "Editor (todos os projetos)".
- O dicionário pessoal do corretor passa a ficar com os dados do TexDesk, e não mais no navegador. As palavras já adicionadas são levadas automaticamente, e a lista pode ser revista nas Configurações.
- Projetos criados a partir de um modelo aparecem como modificados agora, no topo da lista.

### Corrigido
- Duplicar um projeto com o nome sugerido ("… (cópia)") dava erro de nome inválido: nomes de projeto agora aceitam parênteses.

## [0.2.0] - 2026-10-27

Ferramentas de escrita: busca no PDF e no projeto, corretor ortográfico, contagem de palavras e histórico de versões.

### Adicionado
- Busca no PDF compilado (Ctrl+F com o PDF selecionado), sem diferenciar maiúsculas nem acentos, com as ocorrências destacadas nas páginas.
- Busca em todos os arquivos do projeto (Ctrl+Shift+F), com opções de maiúsculas, palavra inteira e expressão regular.
- Contagem de palavras do documento, com texto, títulos, legendas e fórmulas separados, e a contagem do PDF compilado.
- Histórico de versões: o TexDesk guarda versões automaticamente enquanto você edita (e antes de apagar ou mover arquivos), e você pode salvar versões com nome, ver o que mudou e restaurar um arquivo ou o projeto inteiro.
- Corretor ortográfico offline com os dicionários do LibreOffice, em 8 idiomas. Ele detecta o idioma do documento, não sublinha comandos, fórmulas nem rótulos, e mostra sugestões no clique direito.
- Registro de erros e eventos em `logs/texdesk.log` (com rotação): erros inesperados com o rastro completo, compilações e falhas de sincronização com o Drive.
- O painel do Google Drive mostra onde o acesso à conta está guardado.
- Ao abrir, o TexDesk instala sozinho as dependências Python que faltarem depois de uma atualização.

### Alterado
- README reescrito, com capturas de tela, atalhos de teclado e solução de problemas.
- O servidor passa a ser o waitress, no lugar do servidor de desenvolvimento do Flask.
- Painel do Google Drive redesenhado: busca de projetos, projetos com problema agrupados no topo, barra de progresso só durante o envio e explicações recolhidas em "Como funciona a sincronização".
- A lista de projetos ficou cerca de 5 vezes mais rápida (~200 ms para ~37 ms com 58 projetos) e não fica mais lenta conforme os projetos crescem: a data de modificação de cada projeto agora vem de um cache.
- O token do Google Drive passa a ficar no cofre de senhas do sistema (Gerenciador de Credenciais do Windows, Chaves do macOS, Secret Service do Linux). Um `token.json` existente é migrado automaticamente, sem precisar conectar de novo.
- A saída do compilador não mostra mais o aviso "Fontconfig error" nem as linhas repetidas de cada passada do TeX.
- A barra do visualizador de PDF fica compacta no celular.

### Corrigido
- Erros internos do servidor (500) agora chegam à interface como mensagem, em vez de uma página HTML.
- Documentos com bibliografia compilam até 2 vezes mais rápido: um defeito do Tectonic 0.15 fazia o TeX rodar sempre 6 vezes. Agora são 3 passadas, e o TexDesk compila de novo no modo automático se o log ainda pedir outra.

## [0.1.0] - 2026-10-26

Primeira versão pública.

### Editor e compilação
- Editor LaTeX no navegador (CodeMirror) com realce de sintaxe, autocompletar de comandos, ambientes, `\ref`, `\cite` e pacotes, busca e salvamento automático.
- Compilação com o Tectonic (XeTeX), com BibTeX e biber automáticos. O PDF é gerado mesmo quando há erros.
- Painel de logs com erros, avisos e caixas overfull/underfull no arquivo e na linha certos, inclusive em arquivos incluídos com `\input`.
- Visualizador de PDF (PDF.js) com zoom, contagem de páginas e troca de página digitada.
- SyncTeX nos dois sentidos: clique duplo no PDF leva ao código, e um botão leva do código ao PDF.
- Árvore de arquivos com pastas, envio por arrastar e soltar, renomear, mover e definir o documento principal.
- Shell-escape opcional por projeto (para o `minted`), com limpeza automática dos arquivos intermediários.

### Projetos
- Painel de projetos com busca, miniatura da primeira página (em pé ou deitada) e prévia ampliada ao passar o mouse.
- Modelos para começar: em branco, [Slides IFMG](https://github.com/ribeiromarcos/ifslides2024) e [Artigo IFMG](https://github.com/ribeiromarcos/iftex2024).
- Importar e exportar projetos em `.zip`, renomear, duplicar e excluir.

### Google Drive
- Sincronização opcional dos projetos com o Google Drive, a cada 5 segundos durante a edição, enviando só os arquivos alterados.
- Importação dos projetos que já estão no Drive ao conectar a conta em outro computador.
- Permissão mínima (`drive.file`): o app só enxerga os arquivos que ele mesmo criou.

### Instalação
- Pacotes por sistema (Windows, Linux x64 e ARM64, macOS Apple Silicon e Intel), já com o Tectonic e o biber.
- A instalação pré-baixa os pacotes LaTeX dos modelos, para o primeiro documento compilar em segundos.
- Funciona sem internet depois de instalado: o editor e o visualizador de PDF vêm junto com o projeto.

### Segurança
- O servidor local recusa requisições de outros sites (CSRF) e de outros domínios (DNS rebinding).

[Não lançado]: https://github.com/hugocesarleal/texdesk/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/hugocesarleal/texdesk/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/hugocesarleal/texdesk/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/hugocesarleal/texdesk/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/hugocesarleal/texdesk/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/hugocesarleal/texdesk/releases/tag/v0.1.0
