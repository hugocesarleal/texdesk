// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Indicador do Google Drive, dados do autocompletar e inicialização (carregado por último).

// ------------------------------------------------------------ Google Drive
let driveTimer = null;
async function pollDrive() {
  clearTimeout(driveTimer);
  const el = $("#drive-state");
  let st;
  try { st = await api(`${P}/drive`); } catch (e) { st = null; }
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

async function loadMeta() {
  try { projectMeta = await api(`${P}/meta`); } catch (e) { /* ignore */ }
}
setInterval(loadMeta, 15000);

// ------------------------------------------------------------ início
(async function init() {
  try {
    state.settings = await api(`${P}/settings`);
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
  compile({ auto: true });
})();
