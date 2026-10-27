# Histórico de mudanças

As mudanças relevantes de cada versão ficam registradas aqui. O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), e as versões seguem o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- Registro de erros e eventos em `logs/texdesk.log` (com rotação): erros inesperados com o rastro completo, compilações e falhas de sincronização com o Drive.
- O painel do Google Drive mostra onde o acesso à conta está guardado.
- Ao abrir, o TexDesk instala sozinho as dependências Python que faltarem depois de uma atualização.

### Alterado
- O servidor passa a ser o waitress, no lugar do servidor de desenvolvimento do Flask.
- Painel do Google Drive redesenhado: busca de projetos, projetos com problema agrupados no topo, barra de progresso só durante o envio e explicações recolhidas em "Como funciona a sincronização".
- A lista de projetos ficou cerca de 5 vezes mais rápida (~200 ms para ~37 ms com 58 projetos) e não fica mais lenta conforme os projetos crescem: a data de modificação de cada projeto agora vem de um cache.
- O token do Google Drive passa a ficar no cofre de senhas do sistema (Gerenciador de Credenciais do Windows, Chaves do macOS, Secret Service do Linux). Um `token.json` existente é migrado automaticamente, sem precisar conectar de novo.

### Corrigido
- Erros internos do servidor (500) agora chegam à interface como mensagem, em vez de uma página HTML.

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

[Não lançado]: https://github.com/hugocesarleal/texdesk/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/hugocesarleal/texdesk/releases/tag/v0.1.0
