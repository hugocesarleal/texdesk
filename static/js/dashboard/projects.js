// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Painel de projetos: lista, busca, ordem, etiquetas, miniaturas, prévia ampliada e ações
// (fixar, renomear, duplicar, baixar, excluir, enviar .zip). Carregado primeiro: define $,
// projects e load().

const $ = (s) => document.querySelector(s);
$("#new").innerHTML = icon("plus") + "Novo projeto";
$("#upload").innerHTML = icon("upload") + "Enviar .zip";
let projects = [];
const dashStore = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* sem storage */ } },
};
let tagFilter = dashStore.get("dashTag", "");
$("#sort").value = dashStore.get("dashSort", "recent");

async function load() {
  projects = await api("/api/projects");
  render();
  fillThumbnails();
  refreshTrash();
}

const SORTS = {
  recent: (a, b) => b.modified - a.modified,
  old: (a, b) => a.modified - b.modified,
  az: (a, b) => a.name.localeCompare(b.name, "pt-BR", { numeric: true, sensitivity: "base" }),
  za: (a, b) => b.name.localeCompare(a.name, "pt-BR", { numeric: true, sensitivity: "base" }),
};

function renderTags() {
  const all = [...new Set(projects.flatMap((p) => p.tags || []))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  if (tagFilter && !all.includes(tagFilter)) tagFilter = "";
  $("#tags").hidden = !all.length;
  $("#tags").innerHTML = all.length ? `${icon("tag")}<button class="chip ${tagFilter ? "" : "on"}" data-tag="">Todos</button>`
    + all.map((t) => `<button class="chip ${t === tagFilter ? "on" : ""}" data-tag="${esc(t)}">${esc(t)}</button>`).join("") : "";
}

function render() {
  renderTags();
  const q = $("#search").value.toLowerCase();
  const items = projects
    .filter((p) => (p.name.toLowerCase().includes(q) || (p.tags || []).some((t) => t.toLowerCase().includes(q)))
      && (!tagFilter || (p.tags || []).includes(tagFilter)))
    .sort((a, b) => (b.pinned - a.pinned) || SORTS[$("#sort").value || "recent"](a, b));
  if (!items.length) {
    $("#list").innerHTML = `<div class="empty">${projects.length ? "Nenhum projeto encontrado." : "Você ainda não tem projetos. Crie um para começar."}</div>`;
    return;
  }
  $("#list").innerHTML = `<table class="proj-table"><thead><tr><th colspan="2">Nome</th><th class="when">Última modificação</th><th></th></tr></thead><tbody>
    ${items.map((p) => p.importing ? importRow(p) : `<tr data-name="${esc(p.name)}" class="${p.pinned ? "pinned" : ""}">
      <td class="thumb"><a href="/project/${encodeURIComponent(p.name)}" tabindex="-1">${thumbHtml(p)}</a></td>
      <td class="name">${p.pinned ? `<span class="pin-mark" title="Fixado no topo">${icon("pin")}</span>` : ""}<a href="/project/${encodeURIComponent(p.name)}">${esc(p.name)}</a> ${driveIcon(p.drive)}${githubIcon(p.github)}
        ${(p.tags || []).length ? `<div class="proj-tags">${p.tags.map((t) => `<button class="chip small" data-tag="${esc(t)}" title="Mostrar só os projetos com esta etiqueta">${esc(t)}</button>`).join("")}</div>` : ""}</td>
      <td class="when">${timeAgo(p.modified)}</td>
      <td class="acts">
        <button class="icon-btn ${p.pinned ? "on" : ""}" data-act="pin" title="${p.pinned ? "Desafixar" : "Fixar no topo"}">${icon("pin")}</button>
        <button class="icon-btn" data-act="tags" title="Etiquetas">${icon("tag")}</button>
        <button class="icon-btn" data-act="rename" title="Renomear">${icon("edit")}</button>
        <button class="icon-btn" data-act="clone" title="Duplicar">${icon("copy")}</button>
        <button class="icon-btn" data-act="zip" title="Baixar .zip">${icon("download")}</button>
        <button class="icon-btn" data-act="delete" title="Excluir">${icon("trash")}</button>
      </td></tr>`).join("")}</tbody></table>`;
}

// projeto vindo do Drive que ainda está sendo baixado (ou cuja importação falhou)
function importRow(p) {
  const st = p.importing;
  const src = IMPORT_SOURCES[st.source] || IMPORT_SOURCES.drive;
  const err = st.state === "error";
  const pct = st.total ? Math.round((st.done / st.total) * 100) : 0;
  const what = err ? `Não foi possível importar do ${src.label}: ${esc(st.error)}`
    : st.state === "queued" ? `Na fila para importar do ${src.label}`
    : st.total == null ? `Importando do ${src.label}…`
    : `Importando do ${src.label}: ${st.done} de ${st.total} ${st.total === 1 ? "arquivo" : "arquivos"}`;
  return `<tr data-name="${esc(p.name)}" data-source="${esc(st.source || "drive")}" class="importing${err ? " import-err" : ""}">
    <td class="thumb"><span class="thumb-slot"><span class="thumb-empty">${icon(err ? "cloudOff" : "cloud", err ? "" : "pulse")}</span></span></td>
    <td class="name"><span class="nm">${esc(p.name)}</span><div class="import-st">${what}</div>
      ${err ? "" : `<div class="import-bar"><span style="width:${pct}%"></span></div>`}</td>
    <td class="when">${err ? "" : st.state === "queued" ? "na fila" : `${pct}%`}</td>
    <td class="acts">${err ? `<button class="btn small" data-imp="retry">Tentar de novo</button> <button class="btn small" data-imp="dismiss" title="O projeto continua no ${src.short}, em ${src.later}">Descartar</button>` : ""}</td></tr>`;
}

pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs-3.11.174/pdf.worker.min.js";

function thumbHtml(p) {
  if (!p.thumb) return `<span class="thumb-empty">${icon("file")}</span>`;
  const wide = p.thumbW && p.thumbH && p.thumbW > p.thumbH;
  return `<img class="${wide ? "wide" : "tall"}" src="/api/projects/${encodeURIComponent(p.name)}/thumbnail?v=${p.thumb}" alt="" loading="lazy">`;
}

// miniatura de baixa resolução (versões antigas geravam 240 px): regera uma vez
const thumbOutdated = (x) => !x.thumb || x.thumb < x.pdf || (x.thumbW && Math.max(x.thumbW, x.thumbH) < THUMB_SIZE);

// ------------------------------------------------------------ prévia ampliada ao passar o mouse
const pop = document.createElement("div");
pop.className = "thumb-pop";
pop.hidden = true;
pop.innerHTML = "<img alt=''>";
document.body.appendChild(pop);

function showPop(img) {
  const wide = img.naturalWidth > img.naturalHeight;
  const ratio = img.naturalWidth / img.naturalHeight || 0.707;
  // em pé: até 380 px de altura; deitado: até 460 px de largura (sempre dentro da janela)
  let h = wide ? 460 / ratio : 380;
  h = Math.min(h, innerHeight - 24);
  let w = h * ratio;
  if (w > innerWidth - 24) { w = innerWidth - 24; h = w / ratio; }
  const r = img.getBoundingClientRect();
  let left = r.right + 14;
  if (left + w > innerWidth - 12) left = Math.max(12, r.left - 14 - w);  // sem espaço à direita: abre à esquerda
  const top = Math.min(Math.max(12, r.top + r.height / 2 - h / 2), innerHeight - h - 12);
  const pi = pop.querySelector("img");
  pi.src = img.src;
  // a prévia "cresce" a partir da miniatura: começa do tamanho dela, no lugar dela
  const originX = r.left + r.width / 2 - left, originY = r.top + r.height / 2 - top;
  clearTimeout(popHideTimer);
  Object.assign(pop.style, {
    width: w + "px", height: h + "px", left: left + "px", top: top + "px",
    transformOrigin: `${originX}px ${originY}px`, transition: "none",
    transform: `scale(${r.width / w})`, opacity: "0.4",
  });
  pop.hidden = false;
  void pop.offsetWidth;  // aplica o estado inicial antes de animar
  pop.style.transition = "";
  pop.style.transform = "scale(1)";
  pop.style.opacity = "1";
  popFrom = r.width / w;
}

let popHideTimer = 0, popFrom = 0.2;
function hidePop(animated = true) {
  if (pop.hidden) return;
  if (!animated) { pop.hidden = true; return; }
  pop.style.transform = `scale(${popFrom})`;  // encolhe de volta para a miniatura
  pop.style.opacity = "0";
  popHideTimer = setTimeout(() => { pop.hidden = true; }, 160);
}

$("#list").addEventListener("mouseover", (e) => {
  const img = e.target.closest("td.thumb img");
  if (img && img.complete && img.naturalWidth) showPop(img);
});
$("#list").addEventListener("mouseout", (e) => { if (e.target.closest("td.thumb img")) hidePop(); });
addEventListener("scroll", () => hidePop(false), { passive: true });

// Gera (uma vez) as miniaturas que faltam ou ficaram mais velhas que o PDF compilado.
let thumbQueueRunning = false;
async function fillThumbnails() {
  if (thumbQueueRunning) return;
  thumbQueueRunning = true;
  try {
    for (const p of projects.filter((x) => x.pdf && thumbOutdated(x))) {
      try {
        const size = await saveThumbnail(p.name, p.pdfUrl);
        p.thumb = Date.now() / 1000;
        p.thumbW = size.width;
        p.thumbH = size.height;
        const cell = document.querySelector(`tr[data-name="${CSS.escape(p.name)}"] td.thumb a`);
        if (cell) cell.innerHTML = thumbHtml(p);
      } catch (e) { p.thumb = p.pdf; /* PDF ilegível: não tenta de novo nesta visita */ }
    }
  } finally { thumbQueueRunning = false; }
}

function driveIcon(st) {
  const b = driveBadge(st);
  return b ? `<span class="drive-ind ${b.cls}" title="${esc(b.text)}">${icon(b.icon)}</span>` : "";
}

function githubIcon(st) {
  const b = githubBadge(st);
  if (!b) return "";
  const sh = st.shared;
  const people = sh ? `<span class="drive-ind gh-ind drive-ok" title="${esc(sh.mine ? "Compartilhado pelo GitHub" : `Projeto de @${sh.owner}${st.readOnly ? ", só para leitura" : ""}`)}">${icon("users")}</span>` : "";
  return `<span class="drive-ind gh-ind ${b.cls}" title="${esc(b.text)}">${icon(b.icon)}</span>${people}`;
}

// ------------------------------------------------------------ convites recebidos (GitHub)
async function checkInvites() {
  let items, gh;
  try { [items, gh] = await Promise.all([api("/api/github/invitations"), api("/api/github/status")]); } catch (e) { return; }
  const el = $("#invites");
  // acesso ao GitHub vencido: os commits param até a pessoa entrar de novo
  const expired = gh.authExpired ? `<div class="update-banner invite">${icon("lock")}
      <span><b>O acesso ao GitHub expirou</b> e os commits estão parados. Entre com GitHub de novo: daqui em diante o TexDesk renova o acesso sozinho.</span>
      <button class="btn small primary" data-gh-panel>Entrar de novo</button></div>` : "";
  el.innerHTML = expired + items.map((i) => `<div class="update-banner invite" data-id="${i.id}">${icon("users")}
      <span><b>@${esc(i.from || "alguém")}</b> compartilhou <b>${esc(i.name)}</b> com você (${i.write ? "pode editar" : "só para leitura"}).</span>
      <button class="btn small" data-decline>Recusar</button>
      <button class="btn small primary" data-accept>Aceitar</button></div>`).join("");
  el.querySelector("[data-gh-panel]")?.addEventListener("click", () => openGithubPanel());
  el.querySelectorAll(".invite[data-id]").forEach((row) => {
    const id = row.dataset.id;
    row.querySelector("[data-accept]").onclick = async () => {
      try {
        const r = await api(`/api/github/invitations/${id}/accept`, { method: "POST" });
        toast(`Baixando ${r.name} em segundo plano. Ele aparece na lista e continua sincronizado com quem compartilhou.`, 6000);
        row.remove();
        load();
      } catch (e) { toast(e.message, 6000); }
    };
    row.querySelector("[data-decline]").onclick = async () => {
      if (!(await modal({ title: "Recusar o convite?", body: "<p>O projeto não vem para este computador. Quem compartilhou pode convidar de novo.</p>", ok: "Recusar", danger: true }))) return;
      try { await api(`/api/github/invitations/${id}/decline`, { method: "POST" }); row.remove(); } catch (e) { toast(e.message, 6000); }
    };
  });
}

// atualiza os ícones de sincronização enquanto há envio pendente
// (inclusive a contagem até o commit do GitHub)
const busySync = (st) => st && (st.pending || st.state === "syncing" || st.state === "waiting");
setInterval(async () => {
  if (!projects.some((p) => busySync(p.drive) || busySync(p.github))) return;
  const fresh = await api("/api/projects").catch(() => null);
  if (!fresh) return;
  for (const f of fresh) {
    const p = projects.find((x) => x.name === f.name);
    if (!p) continue;
    p.drive = f.drive;
    p.github = f.github;
    const cell = document.querySelector(`tr[data-name="${CSS.escape(p.name)}"] td.name`);
    if (cell) {
      cell.querySelectorAll(".drive-ind").forEach((x) => x.remove());
      const tags = cell.querySelector(".proj-tags");
      const html = driveIcon(p.drive) + githubIcon(p.github);
      if (tags) tags.insertAdjacentHTML("beforebegin", html); else cell.insertAdjacentHTML("beforeend", html);
    }
  }
}, 3000);

// acompanha as importações do Drive e do GitHub: atualiza o andamento e mostra cada projeto quando chega
const importSig = (list) => JSON.stringify(list.filter((p) => p.importing).map((p) => [p.name, p.importing.state]));
setInterval(async () => {
  if (!projects.some((p) => p.importing && p.importing.state !== "error")) return;
  const fresh = await api("/api/projects").catch(() => null);
  if (!fresh) return;
  if (importSig(fresh) === importSig(projects) && fresh.length === projects.length) {
    // só o andamento mudou: troca as linhas, sem redesenhar a lista
    for (const f of fresh.filter((x) => x.importing)) {
      const row = document.querySelector(`tr[data-name="${CSS.escape(f.name)}"]`);
      if (row) row.outerHTML = importRow(f);
    }
    projects = fresh;
    return;
  }
  const was = new Map(projects.filter((p) => p.importing).map((p) => [p.name, p.importing.state]));
  const done = fresh.filter((f) => !f.importing && was.has(f.name) && was.get(f.name) !== "error").map((f) => f.name);
  const failed = fresh.filter((f) => f.importing?.state === "error" && was.get(f.name) !== "error").map((f) => f.name);
  projects = fresh;
  render();
  fillThumbnails();
  if (done.length) toast(done.length === 1 ? `${done[0]} foi importado` : `${done.length} projetos importados`);
  if (failed.length) toast(`Não foi possível importar ${failed.join(", ")}. Veja na lista.`, 6000);
}, 1000);

$("#search").oninput = render;
$("#sort").onchange = () => { dashStore.set("dashSort", $("#sort").value); render(); };

function setTagFilter(t) {
  tagFilter = t === tagFilter ? "" : t;
  dashStore.set("dashTag", tagFilter);
  render();
}
$("#tags").onclick = (e) => { const c = e.target.closest("[data-tag]"); if (c) setTagFilter(c.dataset.tag); };

$("#list").onclick = async (e) => {
  const chip = e.target.closest("[data-tag]");
  if (chip) { setTagFilter(chip.dataset.tag); return; }
  const imp = e.target.closest("button[data-imp]");
  if (imp) {
    const name = imp.closest("tr").dataset.name;
    try {
      const src = IMPORT_SOURCES[imp.closest("tr").dataset.source] || IMPORT_SOURCES.drive;
      await api(`${src.api}/import/${imp.dataset.imp}`, { json: { name } });
      load();
    } catch (err) { toast(err.message); }
    return;
  }
  const b = e.target.closest("button[data-act]");
  if (!b) return;
  const name = b.closest("tr").dataset.name;
  const enc = encodeURIComponent(name);
  const p = projects.find((x) => x.name === name);
  try {
    if (b.dataset.act === "pin") {
      const r = await api(`/api/projects/${enc}/organize`, { json: { pinned: !p.pinned } });
      p.pinned = r.pinned;
      render();
    }
    if (b.dataset.act === "tags") {
      const known = [...new Set(projects.flatMap((x) => x.tags || []))];
      const r = await modal({
        title: "Etiquetas",
        fields: [{ name: "tags", label: `Etiquetas de ${name}, separadas por vírgula`, value: (p.tags || []).join(", "), placeholder: "TCC, artigos, 2026",
          hint: known.length ? `Já usadas: ${known.map(esc).join(", ")}` : "Use etiquetas para agrupar projetos e filtrar a lista." }],
        ok: "Salvar",
      });
      if (!r) return;
      const res = await api(`/api/projects/${enc}/organize`, { json: { tags: r.tags.split(",").map((t) => t.trim()).filter(Boolean) } });
      p.tags = res.tags;
      render();
    }
    if (b.dataset.act === "zip") location.href = `/api/projects/${enc}/zip`;
    if (b.dataset.act === "rename") {
      const r = await modal({ title: "Renomear projeto", fields: [{ name: "name", label: "Novo nome", value: name }], ok: "Renomear" });
      if (r) { await api(`/api/projects/${enc}/rename`, { json: r }); load(); }
    }
    if (b.dataset.act === "clone") {
      const r = await modal({ title: "Duplicar projeto", fields: [{ name: "name", label: "Nome da cópia", value: name + " (cópia)" }], ok: "Duplicar" });
      if (r) { await api(`/api/projects/${enc}/clone`, { json: r }); load(); }
    }
    if (b.dataset.act === "delete") {
      const r = await modal({ title: "Excluir projeto", body: `<p>Mover <b>${esc(name)}</b> para a lixeira?</p><p class="note">Ele fica 30 dias na lixeira, com o histórico de versões, e pode ser restaurado nesse prazo. Enquanto estiver na lixeira, continua no Google Drive e no GitHub; ao ser apagado de vez, sai de lá também.</p>`, ok: "Mover para a lixeira", danger: true });
      if (r) { await api(`/api/projects/${enc}`, { method: "DELETE" }); toast(`${name} foi para a lixeira`); load(); }
    }
  } catch (err) { toast(err.message); }
};

$("#upload").onclick = () => $("#zipfile").click();
$("#zipfile").onchange = async () => {
  const f = $("#zipfile").files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  try {
    const p = await api("/api/projects/upload", { method: "POST", body: fd });
    location.href = `/project/${encodeURIComponent(p.name)}`;
  } catch (err) { toast(err.message); }
  $("#zipfile").value = "";
};

// ------------------------------------------------------------ lixeira
let trashCount = 0;
async function refreshTrash() {
  let items = [];
  try { items = await api("/api/trash"); } catch (e) { /* ignora */ }
  trashCount = items.length;
  $("#trash").innerHTML = icon("trash") + `<span class="lbl">Lixeira</span>` + (trashCount ? ` <span class="count">${trashCount}</span>` : "");
  return items;
}

const daysLeft = (ts) => Math.max(0, Math.ceil((ts - Date.now() / 1000) / 86400));
const fmtSize = (b) => (b < 1024 * 1024 ? `${Math.max(1, Math.round(b / 1024))} KB` : `${(b / 1024 / 1024).toFixed(1).replace(".", ",")} MB`);

// ------------------------------------------------------------ aparência (tema de cores)
$("#appearance").innerHTML = icon("moon") + '<span class="lbl">Aparência</span>';
$("#appearance").onclick = async () => {
  const dlg = modal({ title: "Aparência", cls: "wide", fields: [{ name: "theme", type: "html", html: themePickerHtml() }], ok: "Salvar" });
  const undo = previewThemes(document.querySelector(".modal.wide"));
  const r = await dlg;
  if (r) saveTheme(r.theme); else undo();
};

$("#trash").onclick = async () => {
  const p = panel({ title: "Lixeira", cls: "trash", body: '<p class="note">Carregando…</p>' });
  let remoteNote = "";
  async function show() {
    const items = await refreshTrash();
    const pending = await api("/api/trash/remote").catch(() => []);
    remoteNote = pending.length ? `<div class="dp-status busy"><span class="ic">${icon("cloudUp")}</span><div class="grow">
        <b>Ainda apagando ${plural(pending.length, "item", "itens")} do Google Drive ou do GitHub</b>
        <small>${pending.some((x) => x.kind === "github-repo" && !x.error) ? "Para apagar o repositório de um projeto compartilhado, entre com GitHub de novo (painel → GitHub). " : ""}O TexDesk tenta de novo sozinho${pending.some((x) => x.error) ? " (sem conexão agora)" : ""}.</small></div></div>` : "";
    p.el.innerHTML = items.length
      ? `<p class="note">Projetos excluídos ficam aqui por 30 dias, com o histórico de versões. Depois disso são apagados de vez, também do Google Drive e do GitHub.</p>
        ${remoteNote}
        <div class="trash-list">${items.map((it) => `<div class="trash-row" data-id="${it.id}">
          <div class="who"><b>${esc(it.name)}</b><small>Excluído ${timeAgo(it.deleted)} · ${fmtSize(it.size || 0)} · apagado de vez em ${plural(daysLeft(it.expires), "dia")}</small></div>
          <button class="btn small" data-restore>${icon("restore")}Restaurar</button>
          <button class="icon-btn" data-remove title="Apagar de vez">${icon("trash")}</button></div>`).join("")}</div>
        <div class="trash-foot"><button class="btn small danger" data-empty>Esvaziar lixeira</button></div>`
      : '<p class="empty">A lixeira está vazia.</p>';
  }
  p.el.onclick = async (e) => {
    const row = e.target.closest(".trash-row");
    try {
      if (row && e.target.closest("[data-restore]")) {
        const r = await api(`/api/trash/${row.dataset.id}/restore`, { method: "POST", json: {} });
        toast(`${r.name} foi restaurado`);
        await show();
        load();
      } else if (row && e.target.closest("[data-remove]")) {
        const name = row.querySelector("b").textContent;
        if (!await modal({ title: "Apagar de vez", body: `<p>Apagar <b>${esc(name)}</b> de vez? Isso não pode ser desfeito.</p><p class="note">Ele também é apagado do Google Drive (vai para a lixeira do Drive) e do GitHub. Se foi compartilhado por você, o repositório dele é apagado e as pessoas perdem o acesso; se foi compartilhado com você, você só sai do projeto.</p>`, ok: "Apagar", danger: true })) return;
        await api(`/api/trash/${row.dataset.id}`, { method: "DELETE" });
        await show();
      } else if (e.target.closest("[data-empty]")) {
        if (!await modal({ title: "Esvaziar lixeira", body: `<p>Apagar de vez ${plural(trashCount, "projeto")} da lixeira? Isso não pode ser desfeito.</p><p class="note">Eles também são apagados do Google Drive e do GitHub (inclusive o repositório dos que você compartilhou).</p>`, ok: "Esvaziar", danger: true })) return;
        await api("/api/trash", { method: "DELETE" });
        await show();
      }
    } catch (err) { toast(err.message); }
  };
  show();
};

// ------------------------------------------------------------ aviso de versão nova
async function checkUpdate() {
  let r;
  try { r = await api("/api/update"); } catch (e) { return; }
  if (!r || !r.newer || dashStore.get("updateDismissed", "") === r.latest) return;
  const el = $("#update");
  el.innerHTML = `${icon("info")}<span>Há uma versão nova do TexDesk: <b>${esc(r.latest)}</b> (você usa a ${esc(r.current)}).</span>
    <a class="btn small" href="${esc(r.url)}" target="_blank" rel="noopener">Ver novidades</a>
    ${r.install ? `<button class="btn small primary" data-install>Atualizar agora</button>` : ""}
    <button class="icon-btn" data-dismiss title="Dispensar">${icon("close")}</button>`;
  el.hidden = false;
  el.querySelector("[data-dismiss]").onclick = () => { dashStore.set("updateDismissed", r.latest); el.hidden = true; };
  const btn = el.querySelector("[data-install]");
  if (btn) btn.onclick = () => installUpdate(r);
}

// baixa e instala a versão nova pelo servidor, acompanha o progresso e recarrega a página
// quando o servidor novo abrir (ele reinicia na mesma janela do iniciar.bat/.sh)
async function installUpdate(r) {
  const ok = await modal({
    title: `Atualizar para a versão ${r.latest}?`,
    ok: "Atualizar",
    body: `<p>${r.install === "git"
      ? "O TexDesk vai rodar <code>git pull</code> na pasta dele e reiniciar."
      : "O TexDesk vai baixar o pacote novo do GitHub, instalar por cima da versão atual e reiniciar."}
      Leva menos de um minuto.</p>
      <p class="muted small">Seus projetos, PDFs, histórico e a conexão com o Google Drive ficam como estão.
      Se houver documentos abertos em outras abas, recarregue essas abas (F5) depois da atualização.</p>`,
  });
  if (!ok) return;
  const el = $("#update");
  const show = (text, percent = null) => {
    el.innerHTML = `${icon("refresh", "spin")}<span>${esc(text)}</span>` +
      (percent !== null ? `<progress max="100" value="${percent}"></progress>` : "");
  };
  show("Preparando a atualização…");
  let s;
  try { s = await api("/api/update/install", { json: {} }); } catch (e) { return updateFailed(e.message, r); }
  const boot = s.boot;
  const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
  for (;;) {
    await sleep(700);
    // sem resposta: o servidor está reiniciando. Respondeu com outro "boot" (ou sem esta rota,
    // numa versão que ainda não a tinha): é o servidor novo, e a página recarrega
    let res = null;
    try { res = await fetch("/api/update/status", { cache: "no-store" }); } catch (e) { /* reiniciando */ }
    s = res && res.ok ? await res.json().catch(() => null) : null;
    if (res && (!res.ok || (s && s.boot !== boot))) { location.reload(); return; }
    if (!s) { show("Reiniciando o TexDesk…"); continue; }
    if (s.stage === "error") return updateFailed(s.error, r);
    if (s.stage === "downloading") show(`Baixando a versão ${s.version}… ${s.percent}%`, s.percent);
    else if (s.stage === "installing") show("Instalando…");
    else if (s.stage === "restarting") show("Reiniciando o TexDesk…");
  }
}

function updateFailed(message, r) {
  const el = $("#update");
  el.innerHTML = `${icon("info")}<span>${esc(message)}</span>
    <a class="btn small" href="${esc(r.url)}" target="_blank" rel="noopener">Baixar no GitHub</a>
    <button class="btn small primary" data-retry>Tentar de novo</button>`;
  el.querySelector("[data-retry]").onclick = () => installUpdate(r);
}

// ------------------------------------------------------------ atalho na área de trabalho
// Na primeira abertura pergunta se quer o atalho; se a pasta do TexDesk mudou de lugar,
// pergunta se quer apontar o atalho para a pasta nova. O botão no fim da página cria de novo.
const START_SCRIPT = { windows: "iniciar.bat", linux: "iniciar.sh", macos: "iniciar.sh" };

async function checkShortcut() {
  let s;
  try { s = await api("/api/shortcut"); } catch (e) { return; }
  $("#shortcut").innerHTML = icon("external") + '<span class="lbl">Atalho</span>';
  $("#shortcut").hidden = false;
  $("#shortcut").onclick = () => askShortcut(s, true);
  // outra janela já aberta (ex.: importar do Drive): pergunta na próxima vez
  if (s.ask && !document.querySelector(".modal-bg")) askShortcut(s, false);
}

async function askShortcut(s, fromButton) {
  const script = START_SCRIPT[s.system] || "iniciar";
  const moved = s.ask === "update" && !fromButton;
  const ok = await modal({
    title: moved ? "Atualizar o atalho da área de trabalho?" : "Criar um atalho na área de trabalho?",
    ok: moved ? "Atualizar o atalho" : (s.exists ? "Recriar o atalho" : "Criar atalho"),
    cancel: fromButton ? "Cancelar" : "Agora não",
    body: moved
      ? `<p>A pasta do TexDesk mudou de lugar, e o atalho <b>TexDesk</b> da área de trabalho ainda abre a pasta antiga.</p>
         <p class="muted small">Antes: <code>${esc(s.oldRoot || "")}</code><br>Agora: <code>${esc(s.root)}</code></p>`
      : `<p class="muted small">Se mudar a pasta do TexDesk de lugar, abra pelo <code>${esc(script)}</code> no lugar novo para atualizar o atalho.</p>`,
  });
  if (!ok) {
    if (!fromButton) api("/api/shortcut/decline", { json: {} }).catch(() => {});
    return;
  }
  try {
    const r = await api("/api/shortcut", { json: {} });
    toast(moved ? "Atalho atualizado." : "Atalho criado na área de trabalho.");
    s.exists = true;
    s.ask = null;
    s.path = r.path;
  } catch (e) {
    toast(e.message, 6000);
  }
}

// ------------------------------------------------------------ instalar como aplicativo
// Chrome e Edge oferecem instalar o TexDesk numa janela própria (com o manifesto do site)
let installPrompt = null;
addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  $("#install").innerHTML = icon("install") + '<span class="lbl">Instalar app</span>';
  $("#install").hidden = false;
});
$("#install").onclick = async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  const { outcome } = await installPrompt.userChoice;
  if (outcome === "accepted") $("#install").hidden = true;
  installPrompt = null;
};
addEventListener("appinstalled", () => { $("#install").hidden = true; });
