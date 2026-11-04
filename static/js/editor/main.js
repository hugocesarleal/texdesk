// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Indicador do Google Drive, dados do autocompletar e inicialização (carregado por último).

// ------------------------------------------------------------ Google Drive
// Enquanto o projeto está aberto, o servidor confere a cada ~10 s se outro computador mexeu
// nele (lendo só o arquivo de versão no Drive). O que chegar é gravado no disco, e os arquivos
// abertos mostram a mudança sendo digitada (live.js). Trechos alterados nos dois computadores
// ao mesmo tempo vêm em st.conflicts, para o usuário escolher.
const DRIVE_CHECK_MS = 10000;
let driveTimer = null;
let lastDriveCheck = 0;
let seenReceived = Date.now() / 1000;  // avisos do que chegou antes de abrir a página não aparecem
const shownConflicts = new Set();
let conflictOpen = false;

async function pollDrive() {
  clearTimeout(driveTimer);
  const el = $("#drive-state");
  let st;
  const every = document.hidden ? DRIVE_CHECK_MS * 6 : DRIVE_CHECK_MS;
  const check = state.settings.driveSync && Date.now() - lastDriveCheck >= every;
  try {
    st = await api(`${P}/drive${check ? "/check" : ""}`, check ? { method: "POST" } : {});
    if (check) lastDriveCheck = Date.now();
  } catch (e) { st = null; }
  if (st) driveNews(st);
  const b = driveBadge(st);
  el.hidden = !b;
  if (b) {
    el.className = `tb-btn drive-ind ${b.cls}`;
    el.title = b.text + (st.state === "error" ? "\nClique para tentar de novo." : "\nClique para sincronizar agora.");
    const label = st.state === "error" ? "Erro no Drive" : b.cls === "drive-busy" ? "Sincronizando…" : b.cls === "drive-off" ? "Drive desconectado" : "No Drive";
    el.innerHTML = icon(b.icon) + `<span class="hide-sm">${label}</span>`;
  }
  // mais rápido enquanto há envio pendente; devagar quando ocioso
  const busy = st && st.enabled && (st.pending || st.state === "syncing");
  driveTimer = setTimeout(pollDrive, busy ? 1500 : st && st.enabled ? 5000 : 15000);
}
$("#drive-state").onclick = async () => {
  await saveAll();
  try { await api(`${P}/drive/sync`, { method: "POST" }); } catch (e) { toast(e.message); }
  pollDrive();
};
document.addEventListener("visibilitychange", () => { if (!document.hidden && state.settings.driveSync) pollDrive(); });

// O que chegou do Drive desde a última olhada: aviso dos arquivos e, se houver, os conflitos.
function driveNews(st) {
  const r = st.received;
  if (r && r.at > seenReceived) {
    seenReceived = r.at;
    const from = r.computer ? ` (de ${r.computer})` : "";
    const names = r.files.slice(0, 3).join(", ") + (r.files.length > 3 ? ` e mais ${r.files.length - 3}` : "");
    toast(`Alterações recebidas do Google Drive${from}: ${names}`, 5000);
    checkExternalChanges();  // mostra já a mudança nos arquivos abertos
    loadMeta();
  }
  const next = (st.conflicts || []).find((c) => !shownConflicts.has(c.id));
  if (next && !conflictOpen) showDriveConflict(next);
}

// Um trecho foi alterado aqui e em outro computador ao mesmo tempo. O arquivo já está com o
// trecho daqui (o resto foi juntado); o usuário escolhe se fica assim ou se usa o do outro.
async function showDriveConflict(c) {
  conflictOpen = true;
  shownConflicts.add(c.id);
  const show = (t) => `<pre class="conflict-text">${esc(t) || '<span class="muted">(trecho apagado)</span>'}</pre>`;
  const keepMine = await modal({
    title: "Trecho alterado nos dois computadores",
    cls: "wide",
    body: `<p><b>${esc(c.path)}</b>, linha ${c.line + 1}, foi alterado aqui e em outro computador antes de os dois sincronizarem. O resto do arquivo foi juntado; só este trecho precisa da sua escolha.</p>
      <h3 class="modal-sec">Neste computador (está no arquivo agora)</h3>${show(c.mine)}
      <h3 class="modal-sec">No outro computador</h3>${show(c.theirs)}
      <p class="muted small">A versão de antes da junção fica no Histórico.</p>`,
    ok: "Manter a deste computador",
    cancel: "Usar a do outro computador",
    dismissable: false,
  });
  try {
    await saveAll();  // a troca é feita no disco; nada daqui pode ficar por salvar
    await api(`${P}/drive/conflict`, { json: { id: c.id, use: keepMine ? "mine" : "theirs" } });
    if (!keepMine) checkExternalChanges();
  } catch (e) {
    toast(e.message, 6000);
  } finally {
    conflictOpen = false;
  }
  pollDrive();
}

// Ao abrir o projeto: antes de mostrar os arquivos, traz o que outro computador mudou. Espera
// pouco: se o Drive demorar (internet lenta, muitos projetos sendo conferidos ao iniciar), o
// projeto abre assim mesmo, e o que chegar depois aparece sendo digitado nos arquivos abertos.
const FIRST_CHECK_MAX_MS = 4000;
async function firstDriveCheck() {
  const t0 = Date.now() / 1000;
  let st;
  try { st = await api(`${P}/drive/check`, { method: "POST" }); } catch (e) { return; }
  lastDriveCheck = Date.now();
  if (!st.enabled || !st.connected) return;
  setSaveState("Buscando atualizações do Google Drive…");
  const end = Date.now() + FIRST_CHECK_MAX_MS;
  while (!(st.checkedAt >= t0)) {
    if (Date.now() > end) return;
    await new Promise((r) => setTimeout(r, 300));
    try { st = await api(`${P}/drive`); } catch (e) { return; }
  }
  if (st.state === "error") toast("Não foi possível conferir o Google Drive agora: " + (st.error || ""), 6000);
  else if (st.received && st.received.at >= t0) {
    seenReceived = st.received.at;
    toast(`${st.received.files.length} arquivo(s) atualizado(s) com o que estava no Google Drive.`, 5000);
  }
}

async function loadMeta() {
  try { projectMeta = await api(`${P}/meta`); } catch (e) { /* ignore */ }
}
setInterval(loadMeta, 15000);

// ------------------------------------------------------------ início
(async function init() {
  try {
    state.settings = await api(`${P}/settings`);
    if (state.settings.driveSync) {
      await firstDriveCheck();
      state.settings = await api(`${P}/settings`);  // podem ter vindo do outro computador
    }
    await loadFiles();
  } catch (e) {
    document.body.innerHTML = `<div class="empty">Projeto não encontrado. <a href="/">Voltar</a></div>`;
    return;
  }
  const last = store.get(`open:${PROJECT}`, null);
  const first = state.files.some((f) => f.path === last) ? last : state.settings.main;
  if (first && first.includes("/")) {
    const parts = first.split("/");
    for (let i = 1; i < parts.length; i++) state.openFolders.add(parts.slice(0, i).join("/"));
  }
  await openFile(first);
  loadMeta();
  pollDrive();
  setSaveState("Salvo");
  showLastOrCompile();
})();
