# Política de segurança

## Como reportar uma falha

**Não abra uma issue pública.** Use o relato privado do GitHub:

1. Abra a aba [Security](https://github.com/hugocesarleal/texdesk/security) do repositório.
2. Clique em **Report a vulnerability**.
3. Descreva o problema, como reproduzir e qual o impacto.

O relato fica visível só para os mantenedores até a correção ser publicada. Você recebe uma resposta em até 7 dias, e o crédito pela descoberta no CHANGELOG, se quiser.

## Versões com correções de segurança

Correções de segurança saem sempre na versão mais recente. Mantenha o TexDesk atualizado pela [página de releases](https://github.com/hugocesarleal/texdesk/releases/latest).

## O que considerar

O TexDesk é um servidor web que roda no seu computador, então estes pontos merecem atenção especial:

- **Servidor local:** ele só escuta em `127.0.0.1`, mas qualquer site aberto no navegador consegue mandar requisições para ele. O servidor recusa requisições de outros sites (CSRF) e de outros domínios (DNS rebinding); os testes em `tests/test_security.py` reproduzem esses ataques. Qualquer forma de contornar essas proteções é uma falha de segurança.
- **Shell-escape:** com ele ligado, um documento LaTeX pode executar comandos no computador (`\write18`, `minted`). Ele vem desligado e é uma opção de cada projeto. Só ligue em documentos em que você confia.
- **Google Drive:** o app pede só o escopo `drive.file`, que dá acesso apenas aos arquivos criados por ele. O token de acesso fica no **cofre de senhas do sistema** (Gerenciador de Credenciais no Windows, Chaves no macOS, Secret Service no Linux), na entrada "TexDesk". Sem cofre disponível, como num Linux sem interface gráfica, ele fica em `.drive/token.json`, com permissão só para o dono do arquivo, e o painel do Drive avisa. As credenciais do cliente OAuth (`.drive/credentials.json`) ficam na pasta: para apps instalados, o Google não as considera secretas, mas não compartilhe a pasta `.drive/` (ela está no `.gitignore`). Se o computador for de outra pessoa, use **Desconectar** no painel do Drive: isso revoga o acesso no Google e apaga o token.
- **Registro de erros:** `logs/texdesk.log` guarda erros e eventos, com nomes de projetos e caminhos do computador, mas nunca tokens ou o conteúdo dos documentos. Revise antes de anexar o arquivo a uma issue.
- **Arquivos de projetos de terceiros:** abrir um `.zip` de projeto de outra pessoa é seguro (os caminhos são validados), mas compilar com shell-escape ligado não é.
