// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Painel do Google Drive: configurar credenciais, conectar, sincronizar e baixar projetos.

// ------------------------------------------------------------ painel do Google Drive
$("#drive").innerHTML = icon("cloud") + "Google Drive";
$("#drive").onclick = () => openDrivePanel();

async function openDrivePanel() {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal wide"><h2>Google Drive</h2><div id="drive-body">Carregando…</div>
    <div class="actions"><button class="btn" data-close>Fechar</button></div></div>`;
  const close = () => { clearTimeout(pollTimer); bg.remove(); load(); };
  bg.addEventListener("mousedown", (e) => { if (e.target === bg) close(); });
  bg.querySelector("[data-close]").onclick = close;
  document.body.appendChild(bg);
  const body = bg.querySelector("#drive-body");

  async function refresh() {
    let st;
    try { st = await api("/api/drive/status"); } catch (e) { body.innerHTML = `<div class="err-box">${esc(e.message)}</div>`; return; }

    if (!st.configured) {
      body.innerHTML = `
        <p class="note">Para acessar o Drive, o Google exige credenciais OAuth do seu próprio projeto no Google Cloud. É gratuito, não pede cartão e é feito uma vez só (uns 5 minutos). Abra cada link numa nova aba, com a mesma conta Google que vai usar o Drive.</p>
        <ol class="steps">
          <li><b>Criar o projeto.</b> Abra <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noopener">Novo projeto</a>, digite um nome (ex.: <code>TexDesk</code>), deixe "Local" como está e clique em <b>Criar</b>. Espere a notificação "Projeto criado" (sino no canto superior direito) e clique em <b>Selecionar projeto</b>.
            <br><small>Confira no topo da página, ao lado do logo "Google Cloud", que o seletor mostra <b>TexDesk</b>. Todos os passos abaixo valem para o projeto selecionado ali.</small></li>
          <li><b>Ativar a Google Drive API.</b> Abra a <a href="https://console.cloud.google.com/apis/library/drive.googleapis.com" target="_blank" rel="noopener">página da Google Drive API</a> e clique no botão azul <b>Ativar</b> (em inglês, <b>Enable</b>). Quando terminar, o botão vira <b>Gerenciar</b>: está ativada.
            <br><small>Não achou? Pelo menu ☰ (canto superior esquerdo), vá em <b>APIs e serviços → Biblioteca</b>, digite <code>Google Drive API</code> na busca e clique no resultado com o ícone do Drive. Se a página pedir para "Selecionar um projeto", escolha <b>TexDesk</b>. Cuidado para não escolher a "Google Drive Activity API" nem a "Drive Labels API".</small></li>
          <li><b>Configurar a tela de consentimento.</b> Abra o <a href="https://console.cloud.google.com/auth/overview" target="_blank" rel="noopener">Google Auth Platform</a> e clique em <b>Começar</b> (Get started):
            <br>• <b>Informações do app:</b> nome <code>TexDesk</code> e o seu e-mail como e-mail de suporte → <b>Próxima</b>.
            <br>• <b>Público-alvo:</b> escolha <b>Externo</b> → <b>Próxima</b>.
            <br>• <b>Dados de contato:</b> o seu e-mail → <b>Próxima</b>. Aceite a política e clique em <b>Criar</b>.</li>
          <li><b>Liberar a sua conta.</b> No menu da esquerda do Google Auth Platform, abra <a href="https://console.cloud.google.com/auth/audience" target="_blank" rel="noopener">Público-alvo</a>. Em <b>Usuários de teste</b>, clique em <b>+ Adicionar usuários</b>, digite o seu e-mail do Google e salve.
            <br><small>Sem isso, o login dá o erro "access_denied". Depois de conectar, recomendo clicar em <b>Publicar app</b> nessa mesma página: no modo "Em teste" o Google faz o acesso expirar a cada 7 dias. Publicar é gratuito e, como o app só usa <code>drive.file</code>, não exige verificação.</small></li>
          <li><b>Criar a credencial.</b> Abra <a href="https://console.cloud.google.com/auth/clients" target="_blank" rel="noopener">Clientes</a> → <b>+ Criar cliente</b>. Em <b>Tipo de aplicativo</b>, escolha <b>App para computador</b> (Desktop app), dê um nome qualquer e clique em <b>Criar</b>.</li>
          <li><b>Baixar o JSON.</b> Na janela "Cliente OAuth criado", clique em <b>Fazer o download do JSON</b>. Se a janela já fechou, clique no nome do cliente na lista e use o ícone de download em <b>Chaves secretas do cliente</b>. O arquivo se chama algo como <code>client_secret_….apps.googleusercontent.com.json</code>.</li>
          <li><b>Enviar aqui:</b></li>
        </ol>
        <p><input type="file" id="cred-file" accept=".json,application/json"></p>
        <p class="note">O app pede apenas o escopo <code>drive.file</code>: ele só enxerga os arquivos que ele mesmo criar, nunca o resto do seu Drive.</p>`;
      body.querySelector("#cred-file").onchange = async (e) => {
        const fd = new FormData();
        fd.append("file", e.target.files[0]);
        try { await api("/api/drive/credentials", { method: "POST", body: fd }); refresh(); } catch (err) { toast(err.message, 5000); }
      };
      return;
    }

    if (!st.connected) {
      body.innerHTML = `
        <p>Credenciais configuradas. Agora conecte sua conta Google:</p>
        <p><a class="btn primary" href="/api/drive/connect">${icon("cloud")} Conectar ao Google Drive</a></p>
        <p class="note">Você será levado à tela de login do Google e voltará para cá. Como o app está em modo de teste, o Google mostra um aviso de "app não verificado": clique em <b>Continuar</b>.</p>
        <p class="note">Trocar credenciais: <input type="file" id="cred-file" accept=".json"></p>`;
      body.querySelector("#cred-file").onchange = async (e) => {
        const fd = new FormData();
        fd.append("file", e.target.files[0]);
        try { await api("/api/drive/credentials", { method: "POST", body: fd }); toast("Credenciais atualizadas"); } catch (err) { toast(err.message, 5000); }
      };
      return;
    }

    renderConnected(st);
  }

  // ---- painel conectado: conta, opção global, progresso e lista de projetos
  let tab = "local";
  let remoteCache = null;

  function renderConnected(st) {
    const u = st.user || {};
    const initial = (u.displayName || u.emailAddress || "?").trim()[0].toUpperCase();
    body.innerHTML = `
      <div class="dp-account">
        <div class="dp-avatar">${esc(initial)}</div>
        <div class="who"><b>${esc(u.displayName || "Conta Google")}</b><small>${esc(u.emailAddress || "")}</small></div>
        <a class="btn small" id="dp-open" target="_blank" rel="noopener" hidden>${icon("folderOpen")}Abrir no Drive</a>
        <button class="btn small danger" id="drive-disconnect">Desconectar</button>
      </div>

      <label class="dp-toggle">
        <span class="txt"><b>Sincronizar todos os projetos</b>
          <small>Inclui os projetos criados daqui em diante. Para ligar ou desligar um projeto só, use as Configurações dentro do editor.</small></span>
        <input type="checkbox" id="sync-all" ${st.syncAll ? "checked" : ""}><span class="track" aria-hidden="true"></span>
      </label>

      <div class="dp-progress" id="dp-progress"></div>

      <div class="dp-head">
        <div class="dp-tabs" role="tablist">
          <button role="tab" data-tab="local">Neste computador <span id="dp-n-local"></span></button>
          <button role="tab" data-tab="remote">Só no Drive <span id="dp-n-remote"></span></button>
        </div>
        <button class="btn small" id="dp-sync-now" title="Verifica todos os projetos e envia o que mudou">${icon("refresh")}Sincronizar agora</button>
      </div>
      <div class="dp-list" id="dp-list"><div class="dp-empty">Carregando…</div></div>

      <p class="note">Os projetos ficam na pasta <b>TexDesk</b> do seu Drive. Enquanto você edita, as alterações são enviadas a cada 5 segundos. Arquivos apagados aqui vão para a lixeira do Drive. Excluir um projeto aqui não o apaga do Drive.</p>`;

    body.querySelector("#drive-disconnect").onclick = async () => {
      const ok = await modal({ title: "Desconectar o Google Drive?", body: "<p>A sincronização para. Nada é apagado do Drive nem do computador.</p>", ok: "Desconectar", danger: true });
      if (ok) { await api("/api/drive/disconnect", { method: "POST" }); refresh(); }
    };
    body.querySelector("#sync-all").onchange = async (e) => {
      await api("/api/drive/sync-all", { json: { enabled: e.target.checked } });
      toast(e.target.checked ? "Sincronização ligada para todos os projetos" : "Sincronização desligada para todos os projetos");
      poll();
    };
    body.querySelector("#dp-sync-now").onclick = async () => { await api("/api/drive/sync-now", { method: "POST" }); poll(); };
    body.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { tab = b.dataset.tab; drawList(); if (tab === "remote") loadRemote(); }));
    body.querySelector("#dp-list").onclick = onListClick;
    poll();
    loadRemote();
  }

  let ov = null;
  let pollTimer = null;
  async function poll() {
    clearTimeout(pollTimer);
    if (!bg.isConnected) return;
    try { ov = await api("/api/drive/overview"); } catch (e) { ov = { error: e.message, counts: {}, projects: [] }; }
    drawProgress();
    drawList();
    const busy = ov.counts && ov.counts.pending > 0;
    pollTimer = setTimeout(poll, busy ? 1500 : 5000);
  }

  function drawProgress() {
    const el = body.querySelector("#dp-progress");
    if (!el || !ov) return;
    const c = ov.counts || {};
    const open = body.querySelector("#dp-open");
    if (open && ov.rootId) { open.href = `https://drive.google.com/drive/folders/${ov.rootId}`; open.hidden = false; }
    if (ov.error) { el.className = "dp-progress err"; el.innerHTML = `${icon("cloudOff")}<div><b>Não foi possível consultar o Drive</b><small>${esc(ov.error)}</small></div>`; return; }
    if (!c.total) {
      el.className = "dp-progress idle";
      el.innerHTML = `${icon("cloudOff")}<div><b>Nenhum projeto sincronizado</b><small>Ligue a opção acima ou ative projetos nas configurações do editor.</small></div>`;
      return;
    }
    const pct = Math.round((c.synced / c.total) * 100);
    const last = Math.max(0, ...ov.projects.map((p) => p.lastSync || 0));
    let cls, ic, title, sub;
    if (c.error) {
      cls = "err"; ic = "cloudOff";
      title = `${c.error} projeto${c.error > 1 ? "s" : ""} com erro`;
      sub = "Será tentado de novo automaticamente. Veja os detalhes na lista abaixo.";
    } else if (c.pending) {
      cls = "busy"; ic = "cloudUp";
      title = `Enviando para o Drive… ${c.synced} de ${c.total}`;
      sub = "Pode continuar usando normalmente. O projeto que você estiver editando tem prioridade.";
    } else {
      cls = "ok"; ic = "cloudCheck";
      title = `Tudo salvo no Drive · ${c.total} projeto${c.total > 1 ? "s" : ""}`;
      sub = last ? `Última sincronização ${timeAgo(last)}` : "";
    }
    el.className = `dp-progress ${cls}`;
    el.innerHTML = `${icon(ic)}<div class="grow"><b>${esc(title)}</b><small>${esc(sub)}</small>
      <div class="bar"><span style="width:${pct}%"></span></div></div>`;
  }

  function projState(p) {
    if (p.state === "error") return { o: 0, cls: "drive-err", ic: "cloudOff", txt: p.error || "Erro" };
    if (p.state === "syncing") return { o: 1, cls: "drive-busy", ic: "cloudUp", txt: "Enviando…" };
    if (p.pending || !p.lastSync) return { o: 2, cls: "drive-off", ic: "cloud", txt: "Na fila" };
    return { o: 3, cls: "drive-ok", ic: "cloudCheck", txt: "Salvo " + timeAgo(p.lastSync) };
  }

  function drawList() {
    const el = body.querySelector("#dp-list");
    if (!el) return;
    body.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab));
    const nl = body.querySelector("#dp-n-local"), nr = body.querySelector("#dp-n-remote");
    if (nl && ov) nl.textContent = ov.projects ? ov.projects.length : "";
    const onlyRemote = (remoteCache || []).filter((r) => !r.local);
    if (nr) nr.textContent = remoteCache ? onlyRemote.length : "";

    if (tab === "local") {
      if (!ov) return;
      if (!ov.projects.length) { el.innerHTML = `<div class="dp-empty">Nenhum projeto com sincronização ligada.</div>`; return; }
      const rows = ov.projects.map((p) => ({ p, s: projState(p) })).sort((a, b) => a.s.o - b.s.o || a.p.name.localeCompare(b.p.name));
      el.innerHTML = rows.map(({ p, s }) => `<div class="dp-row">
          <span class="drive-ind ${s.cls}">${icon(s.ic)}</span>
          <a class="nm" href="/project/${encodeURIComponent(p.name)}">${esc(p.name)}</a>
          <span class="st ${s.cls}" title="${esc(s.txt)}">${esc(s.txt)}</span>
        </div>`).join("");
    } else {
      if (!remoteCache) { el.innerHTML = `<div class="dp-empty">Carregando…</div>`; return; }
      el.innerHTML = onlyRemote.length ? onlyRemote.map((r) => `<div class="dp-row">
          <span class="drive-ind drive-off">${icon("folder")}</span>
          <span class="nm">${esc(r.name)}</span>
          <button class="btn small" data-restore="${esc(r.id)}" data-name="${esc(r.name)}">${icon("download")}Baixar</button>
        </div>`).join("") : `<div class="dp-empty">Todos os projetos do Drive já estão neste computador.<br><small>Esta lista serve para baixar projetos em outro computador ou recuperar um projeto excluído aqui.</small></div>`;
    }
  }

  async function loadRemote() {
    try { remoteCache = await api("/api/drive/remote"); } catch (e) { remoteCache = []; toast(e.message, 5000); }
    drawList();
  }

  async function onListClick(e) {
    const b = e.target.closest("[data-restore]");
    if (!b) return;
    const r = await modal({ title: "Baixar projeto do Drive", fields: [{ name: "name", label: "Nome do projeto local", value: b.dataset.name }], ok: "Baixar" });
    if (!r) return;
    b.disabled = true;
    b.textContent = "Baixando…";
    try {
      const res = await api("/api/drive/restore", { json: { id: b.dataset.restore, name: r.name, remoteName: b.dataset.name } });
      toast(`${res.name}: ${res.files} arquivo(s) baixado(s)`);
      await loadRemote();
      poll();
    } catch (err) { toast(err.message, 5000); b.disabled = false; b.textContent = "Baixar"; }
  }

  refresh();
}
