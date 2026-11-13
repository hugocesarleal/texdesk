// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Painel do GitHub: entrar (código digitado em github.com/login/device), situação dos commits,
// sincronizar todos e baixar os projetos que estão só no repositório.

// ------------------------------------------------------------ painel do GitHub
$("#github").innerHTML = icon("git") + "GitHub";
$("#github").onclick = () => openGithubPanel();

async function openGithubPanel() {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal wide"><h2>GitHub</h2><div id="gh-body">Carregando…</div>
    <div class="actions"><button class="btn" data-close>Fechar</button></div></div>`;
  let pollTimer = null, loginTimer = null;
  const close = () => { clearTimeout(pollTimer); clearTimeout(loginTimer); bg.remove(); load(); };
  bg.addEventListener("mousedown", (e) => { if (e.target === bg) close(); });
  bg.querySelector("[data-close]").onclick = close;
  document.body.appendChild(bg);
  const body = bg.querySelector("#gh-body");

  async function refresh() {
    let st;
    try { st = await api("/api/github/status"); } catch (e) { body.innerHTML = `<div class="err-box">${esc(e.message)}</div>`; return; }
    if (!st.configured) {
      body.innerHTML = `<p class="note">O "Entrar com GitHub" ainda não está configurado nesta instalação do TexDesk. Ele chega numa atualização; enquanto isso, use o Google Drive.</p>`;
      return;
    }
    if (!st.connected) return renderLogin();
    renderConnected(st);
  }

  // ---- entrar: o GitHub mostra uma página para digitar o código; esta janela espera sozinha
  function renderLogin() {
    body.innerHTML = `
      <p>Guarde seus projetos num repositório <b>privado</b> do seu GitHub (<code>texdesk-projetos</code>), uma pasta por projeto. O TexDesk faz os commits sozinho, com o histórico de todas as versões.</p>
      <p><button class="btn primary" id="gh-login">${icon("git")} Entrar com GitHub</button></p>
      <p class="note">Não precisa de git instalado nem de criar token: o GitHub mostra uma página onde você digita um código e autoriza o TexDesk. O acesso fica no cofre de senhas deste computador.</p>`;
    body.querySelector("#gh-login").onclick = startLogin;
  }

  async function startLogin() {
    let r;
    try { r = await api("/api/github/login/start", { method: "POST" }); } catch (e) { toast(e.message, 6000); return; }
    body.innerHTML = `
      <ol class="steps gh-steps">
        <li>Copie o código:
          <div class="gh-code"><code id="gh-code">${esc(r.userCode)}</code>
            <button class="btn small" id="gh-copy">${icon("copy")}Copiar</button></div></li>
        <li><a class="btn primary" id="gh-open" href="${esc(r.verificationUri)}" target="_blank" rel="noopener">${icon("external")} Abrir o GitHub</a>
          <br><small>Entre na sua conta, cole o código e clique em <b>Authorize</b>.</small></li>
      </ol>
      <div class="dp-status busy" id="gh-wait"><span class="ic">${icon("refresh", "spin")}</span><div class="grow"><b>Esperando a autorização no GitHub…</b><small>Esta janela continua sozinha. O código vale por ${Math.round(r.expiresIn / 60)} minutos.</small></div></div>`;
    const copy = () => navigator.clipboard?.writeText(r.userCode).then(() => toast("Código copiado"), () => {});
    body.querySelector("#gh-copy").onclick = copy;
    body.querySelector("#gh-open").addEventListener("click", copy);
    const every = Math.max(1, r.interval || 5) * 1000 + 500;
    const tick = async () => {
      if (!bg.isConnected) return;
      let p;
      try { p = await api("/api/github/login/poll", { method: "POST" }); } catch (e) { p = { state: "error", message: e.message }; }
      if (p.state === "pending") { loginTimer = setTimeout(tick, every); return; }
      if (p.state === "done") {
        toast(`GitHub conectado: ${p.repo}`);
        await refresh();
        offerGithubImport();
        return;
      }
      const msg = { expired: "O código expirou antes da autorização.", denied: "A autorização foi recusada no GitHub." }[p.state] || p.message || "Não foi possível entrar.";
      body.querySelector("#gh-wait").outerHTML = `<div class="dp-status err"><span class="ic">${icon("close")}</span><div class="grow"><b>${esc(msg)}</b></div>
        <button class="btn small" id="gh-again">Tentar de novo</button></div>`;
      body.querySelector("#gh-again").onclick = startLogin;
    };
    loginTimer = setTimeout(tick, every);
  }

  // ---- conectado: conta, situação, opção global e lista de projetos
  let tab = "local", remoteCache = null, query = "", ov = null;

  function renderConnected(st) {
    const safe = st.tokenStorage === "keyring";
    body.innerHTML = `
      <div class="dp-account">
        <div class="dp-avatar">${icon("git")}</div>
        <div class="who">
          <b>${esc(st.user || "GitHub")}</b>
          <small>Repositório privado <a href="${esc(st.repoUrl)}" target="_blank" rel="noopener">${esc(st.repo)}</a></small>
          <small class="dp-secure ${safe ? "" : "warn"}">${icon("lock")}${safe ? "Acesso no cofre de senhas do sistema" : "Acesso em arquivo (sem cofre de senhas)"}</small>
        </div>
        <div class="dp-account-actions">
          <a class="btn small" href="${esc(st.repoUrl)}" target="_blank" rel="noopener">${icon("external")}Abrir no GitHub</a>
          <button class="btn small danger" id="gh-disconnect">Desconectar</button>
        </div>
      </div>
      <div class="dp-status" id="gh-progress"></div>
      <label class="dp-toggle">
        <span class="txt"><b>Sincronizar todos os projetos</b>
          <small>Inclui os criados daqui em diante. Para um projeto só, use as Configurações do editor.</small></span>
        <input type="checkbox" id="gh-all" ${st.syncAll ? "checked" : ""}><span class="track" aria-hidden="true"></span>
      </label>
      <div class="dp-section">
        <div class="dp-head">
          <div class="dp-tabs" role="tablist">
            <button role="tab" data-tab="local">Neste computador <span id="gh-n-local"></span></button>
            <button role="tab" data-tab="remote">Só no GitHub <span id="gh-n-remote"></span></button>
          </div>
          <div class="dp-tools">
            <input type="search" id="gh-search" placeholder="Buscar projeto…" aria-label="Buscar projeto">
            <button class="btn small" id="gh-now" title="Faz já os commits que estão esperando os 2 minutos">${icon("cloudUp")}Enviar agora</button>
          </div>
        </div>
        <div class="dp-list" id="gh-list"><div class="dp-empty">Carregando…</div></div>
      </div>
      <details class="dp-help">
        <summary>Como funciona</summary>
        <ul>
          <li>Cada projeto é uma pasta no repositório privado <b>${esc(st.repo)}</b>.</li>
          <li>O commit sai <b>2 minutos depois da última alteração</b>, juntando as edições desse intervalo. Ao fechar o projeto no editor, sai na hora.</li>
          <li>Fechou o TexDesk antes do commit? Ao fechar a janela, ele tenta enviar o que falta; se não der tempo, o envio é feito assim que você abrir o TexDesk de novo. Nada se perde: os arquivos já estão salvos neste computador.</li>
          <li>Com o projeto aberto, o TexDesk confere o GitHub a cada 30 segundos e traz o que outro computador enviou, juntando as edições palavra por palavra.</li>
          <li>Todas as versões ficam no histórico de commits do GitHub. Para tirar o acesso do TexDesk, use <a href="https://github.com/settings/applications" target="_blank" rel="noopener">github.com/settings/applications</a>.</li>
        </ul>
      </details>`;
    body.querySelector("#gh-disconnect").onclick = async () => {
      const ok = await modal({ title: "Desconectar o GitHub?", body: "<p>Os commits param e o acesso à sua conta é apagado deste computador. Nada é apagado do GitHub nem dos seus projetos.</p>", ok: "Desconectar", danger: true });
      if (ok) { await api("/api/github/disconnect", { method: "POST" }); refresh(); }
    };
    body.querySelector("#gh-all").onchange = async (e) => {
      await api("/api/github/sync-all", { json: { enabled: e.target.checked } });
      toast(e.target.checked ? "Todos os projetos vão para o GitHub" : "Sincronização com o GitHub desligada para todos os projetos");
      poll();
    };
    body.querySelector("#gh-now").onclick = async () => {
      await api("/api/github/sync-now", { method: "POST" }).catch((e) => toast(e.message));
      poll();
    };
    body.querySelector("#gh-search").oninput = (e) => { query = e.target.value.trim().toLowerCase(); drawList(); };
    body.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { tab = b.dataset.tab; drawList(); if (tab === "remote") loadRemote(); }));
    body.querySelector("#gh-list").onclick = onListClick;
    poll();
    loadRemote();
  }

  async function poll() {
    clearTimeout(pollTimer);
    if (!bg.isConnected) return;
    try { ov = await api("/api/github/overview"); } catch (e) { ov = { error: e.message, counts: {}, projects: [] }; }
    drawProgress();
    drawList();
    pollTimer = setTimeout(poll, ov.counts && ov.counts.pending ? 1000 : 5000);
  }

  function projState(p) {
    const b = githubBadge(p) || {};
    if (p.state === "error") return { problem: true, o: 0, cls: "drive-err", txt: p.error || "Erro" };
    if (p.state === "syncing") return { problem: true, o: 1, cls: "drive-busy", txt: "Enviando…" };
    if (p.state === "waiting" || p.waitUntil) return { problem: true, o: 1, cls: "drive-busy", txt: "Esperando o limite do GitHub" };
    if (p.pending) return { problem: true, o: 2, cls: "drive-busy", txt: b.seconds ? `Commit em ${Math.floor(b.seconds / 60)}:${String(b.seconds % 60).padStart(2, "0")}` : "Enviando…" };
    if (!p.lastSync) return { problem: true, o: 2, cls: "drive-busy", txt: "Na fila" };
    return { problem: false, o: 3, cls: "drive-ok", txt: p.lastCommit ? "commit " + timeAgo(p.lastCommit.at) : "conferido " + timeAgo(p.lastSync), url: p.lastCommit && p.lastCommit.url };
  }

  function drawProgress() {
    const el = body.querySelector("#gh-progress");
    if (!el || !ov) return;
    const c = ov.counts || {};
    const card = (cls, ic, title, sub) => {
      el.className = `dp-status ${cls}`;
      el.innerHTML = `<span class="ic">${icon(ic)}</span><div class="grow"><b>${esc(title)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</div>`;
    };
    const plural = (n) => `${n} projeto${n > 1 ? "s" : ""}`;
    if (ov.error) return card("err", "cloudOff", "Não foi possível consultar o GitHub", ov.error);
    if (!c.total) return card("idle", "git", "Nenhum projeto sincronizado", "Ligue a opção abaixo ou ative projetos nas Configurações do editor.");
    if (c.error) return card("err", "cloudOff", `${plural(c.error)} com erro`, "O TexDesk tenta de novo sozinho.");
    if (c.pending) {
      const next = Math.min(...ov.projects.filter((p) => p.pending && p.commitAt).map((p) => p.commitAt));
      const s = Number.isFinite(next) ? Math.max(0, Math.round(next - Date.now() / 1000)) : 0;
      return card("busy", "cloudUp", `${plural(c.pending)} com alterações a enviar`,
        s ? `Próximo commit em ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} (2 min depois da última alteração). "Enviar agora" não espera.` : "Enviando…");
    }
    const last = Math.max(0, ...ov.projects.map((p) => (p.lastCommit && p.lastCommit.at) || 0));
    card("ok", "cloudCheck", `Tudo no GitHub · ${plural(c.total)}`, last ? `Último commit ${timeAgo(last)}` : "");
  }

  const matches = (name) => !query || name.toLowerCase().includes(query);

  function drawList() {
    const el = body.querySelector("#gh-list");
    if (!el) return;
    body.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab));
    const onlyRemote = (remoteCache || []).filter((r) => !r.local);
    const nl = body.querySelector("#gh-n-local"), nr = body.querySelector("#gh-n-remote");
    if (nl && ov) nl.textContent = ov.projects ? ov.projects.length : "";
    if (nr) nr.textContent = remoteCache ? onlyRemote.length : "";
    if (tab === "local") {
      if (!ov) return;
      if (!ov.projects.length) { el.innerHTML = `<div class="dp-empty">Nenhum projeto com o GitHub ligado.</div>`; return; }
      const rows = ov.projects.map((p) => ({ p, s: projState(p) })).filter(({ p }) => matches(p.name))
        .sort((a, b) => a.s.o - b.s.o || a.p.name.localeCompare(b.p.name));
      el.innerHTML = rows.length ? rows.map(({ p, s }) => `<div class="dp-row ${s.problem ? "attention" : ""}">
          <span class="drive-ind ${s.cls}">${icon("git")}</span>
          <a class="nm" href="/project/${encodeURIComponent(p.name)}" title="Abrir ${esc(p.name)}">${esc(p.name)}</a>
          ${s.url ? `<a class="st" href="${esc(s.url)}" target="_blank" rel="noopener" title="Ver o commit no GitHub">${esc(s.txt)}</a>` : `<span class="st ${s.problem ? s.cls : ""}" title="${esc(s.txt)}">${esc(s.txt)}</span>`}
        </div>`).join("") : `<div class="dp-empty">Nenhum projeto encontrado.</div>`;
    } else {
      if (!remoteCache) { el.innerHTML = `<div class="dp-empty">Carregando…</div>`; return; }
      const rows = onlyRemote.filter((r) => matches(r.name));
      el.innerHTML = rows.length ? rows.map((r) => `<div class="dp-row">
          <span class="drive-ind drive-off">${icon("folder")}</span>
          <span class="nm">${esc(r.name)}</span>
          <button class="btn small" data-import="${esc(r.id)}">${icon("download")}Baixar</button>
        </div>`).join("")
        : `<div class="dp-empty">Todos os projetos do repositório já estão neste computador.<br><small>Aqui aparecem os projetos que estão só no GitHub: de outro computador ou excluídos deste.</small></div>`;
    }
  }

  async function loadRemote() {
    try { remoteCache = await api("/api/github/remote"); } catch (e) { remoteCache = []; }
    drawList();
  }

  async function onListClick(e) {
    const b = e.target.closest("[data-import]");
    if (!b) return;
    b.disabled = true;
    try {
      const r = await api("/api/github/import", { json: { id: b.dataset.import, name: b.dataset.import } });
      toast(`Baixando ${r.name} do GitHub em segundo plano`);
      close();
    } catch (err) { toast(err.message, 5000); b.disabled = false; }
  }

  refresh();
}
