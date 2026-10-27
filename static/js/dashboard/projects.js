// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Painel de projetos: lista, busca, miniaturas, prévia ampliada e ações (renomear, duplicar,
// baixar, excluir, enviar .zip). Carregado primeiro: define $, projects e load().

const $ = (s) => document.querySelector(s);
$("#new").innerHTML = icon("plus") + "Novo projeto";
$("#upload").innerHTML = icon("upload") + "Enviar .zip";
let projects = [];

async function load() {
  projects = await api("/api/projects");
  render();
  fillThumbnails();
}

function render() {
  const q = $("#search").value.toLowerCase();
  const items = projects.filter((p) => p.name.toLowerCase().includes(q));
  if (!items.length) {
    $("#list").innerHTML = `<div class="empty">${projects.length ? "Nenhum projeto encontrado." : "Você ainda não tem projetos. Crie um para começar."}</div>`;
    return;
  }
  $("#list").innerHTML = `<table class="proj-table"><thead><tr><th colspan="2">Nome</th><th class="when">Última modificação</th><th></th></tr></thead><tbody>
    ${items.map((p) => `<tr data-name="${esc(p.name)}">
      <td class="thumb"><a href="/project/${encodeURIComponent(p.name)}" tabindex="-1">${thumbHtml(p)}</a></td>
      <td class="name"><a href="/project/${encodeURIComponent(p.name)}">${esc(p.name)}</a> ${driveIcon(p.drive)}</td>
      <td class="when">${timeAgo(p.modified)}</td>
      <td class="acts">
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

$("#list").onclick = async (e) => {
  const b = e.target.closest("button[data-act]");
  if (!b) return;
  const name = b.closest("tr").dataset.name;
  const enc = encodeURIComponent(name);
  try {
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
      const r = await modal({ title: "Excluir projeto", body: `<p>Excluir <b>${esc(name)}</b> e todos os seus arquivos? Isso não pode ser desfeito.</p>`, ok: "Excluir", danger: true });
      if (r) { await api(`/api/projects/${enc}`, { method: "DELETE" }); load(); }
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
