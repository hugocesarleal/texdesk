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
    ${items.map((p) => `<tr data-name="${esc(p.name)}" class="${p.pinned ? "pinned" : ""}">
      <td class="thumb"><a href="/project/${encodeURIComponent(p.name)}" tabindex="-1">${thumbHtml(p)}</a></td>
      <td class="name">${p.pinned ? `<span class="pin-mark" title="Fixado no topo">${icon("pin")}</span>` : ""}<a href="/project/${encodeURIComponent(p.name)}">${esc(p.name)}</a> ${driveIcon(p.drive)}
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

// atualiza os ícones de sincronização enquanto há envio pendente
setInterval(async () => {
  if (!projects.some((p) => p.drive && (p.drive.pending || p.drive.state === "syncing"))) return;
  const fresh = await api("/api/projects").catch(() => null);
  if (!fresh) return;
  for (const f of fresh) {
    const p = projects.find((x) => x.name === f.name);
    if (!p) continue;
    p.drive = f.drive;
    const cell = document.querySelector(`tr[data-name="${CSS.escape(p.name)}"] td.name`);
    if (cell) { cell.querySelector(".drive-ind")?.remove(); cell.insertAdjacentHTML("beforeend", driveIcon(p.drive)); }
  }
}, 3000);

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
      const r = await modal({ title: "Excluir projeto", body: `<p>Mover <b>${esc(name)}</b> para a lixeira?</p><p class="note">Ele fica 30 dias na lixeira, com o histórico de versões, e pode ser restaurado nesse prazo.</p>`, ok: "Mover para a lixeira", danger: true });
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
  $("#trash").innerHTML = icon("trash") + (trashCount ? `Lixeira (${trashCount})` : "Lixeira");
  return items;
}

const daysLeft = (ts) => Math.max(0, Math.ceil((ts - Date.now() / 1000) / 86400));
const fmtSize = (b) => (b < 1024 * 1024 ? `${Math.max(1, Math.round(b / 1024))} KB` : `${(b / 1024 / 1024).toFixed(1).replace(".", ",")} MB`);

$("#trash").onclick = async () => {
  const p = panel({ title: "Lixeira", cls: "trash", body: '<p class="note">Carregando…</p>' });
  async function show() {
    const items = await refreshTrash();
    p.el.innerHTML = items.length
      ? `<p class="note">Projetos excluídos ficam aqui por 30 dias, com o histórico de versões. Depois disso são apagados de vez.</p>
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
        if (!await modal({ title: "Apagar de vez", body: `<p>Apagar <b>${esc(name)}</b> de vez? Isso não pode ser desfeito.</p>`, ok: "Apagar", danger: true })) return;
        await api(`/api/trash/${row.dataset.id}`, { method: "DELETE" });
        await show();
      } else if (e.target.closest("[data-empty]")) {
        if (!await modal({ title: "Esvaziar lixeira", body: `<p>Apagar de vez ${plural(trashCount, "projeto")} da lixeira? Isso não pode ser desfeito.</p>`, ok: "Esvaziar", danger: true })) return;
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
    <a class="btn small primary" href="${esc(r.url)}" target="_blank" rel="noopener">Ver novidades</a>
    <button class="icon-btn" data-dismiss title="Dispensar">${icon("close")}</button>`;
  el.hidden = false;
  el.querySelector("[data-dismiss]").onclick = () => { dashStore.set("updateDismissed", r.latest); el.hidden = true; };
}

// ------------------------------------------------------------ instalar como aplicativo
// Chrome e Edge oferecem instalar o TexDesk numa janela própria (com o manifesto do site)
let installPrompt = null;
addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  $("#install").innerHTML = icon("install") + "Instalar app";
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
