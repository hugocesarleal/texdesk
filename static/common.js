// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Utilidades compartilhadas: chamadas à API, ícones, modais e avisos.

async function api(url, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) {
    o.method = o.method || "POST";
    o.headers = { "Content-Type": "application/json", ...(o.headers || {}) };
    o.body = JSON.stringify(o.json);
    delete o.json;
  }
  const r = await fetch(url, o);
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || r.statusText);
  return data;
}

// Ícones adaptados do Feather Icons (MIT) — veja THIRD_PARTY_NOTICES.md
const ICONS = {
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
  folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  folderOpen: '<path d="M6 14l1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>',
  newFile: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M12 18v-6M9 15h6"/>',
  newFolder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><path d="M12 11v6M9 14h6"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  trash: '<path d="M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
  edit: '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  play: '<path d="M5 3l14 9-14 9z"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/>',
  chevron: '<path d="M6 9l6 6 6-6"/>',
  chevronRight: '<path d="M9 18l6-6-6-6"/>',
  home: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  logs: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  zoomIn: '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35M11 8v6M8 11h6"/>',
  zoomOut: '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35M8 11h6"/>',
  fit: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
  arrowRight: '<path d="M5 12h14M12 5l7 7-7 7"/>',
  arrowLeft: '<path d="M19 12H5M12 19l-7-7 7-7"/>',
  star: '<path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z"/>',
  menu: '<path d="M3 12h18M3 6h18M3 18h18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  fileText: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>',
  slides: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  cloud: '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>',
  cloudCheck: '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><path d="M9 14l2 2 4-4"/>',
  cloudUp: '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><path d="M12 17v-5M9.5 14.5L12 12l2.5 2.5"/>',
  cloudOff: '<path d="M22.61 16.95A5 5 0 0 0 18 10h-1.26a8 8 0 0 0-7.05-6M5 5a8 8 0 0 0 4 15h9a5 5 0 0 0 1.7-.3M1 1l22 22"/>',
};

// Estado de sincronização com o Drive -> {icon, cls, text}
function driveBadge(st) {
  if (!st || !st.enabled) return null;
  if (!st.connected) return { icon: "cloudOff", cls: "drive-off", text: "Google Drive desconectado" };
  if (st.state === "error") return { icon: "cloudOff", cls: "drive-err", text: "Erro ao sincronizar: " + (st.error || "") };
  if (st.state === "syncing" || st.pending) return { icon: "cloudUp", cls: "drive-busy", text: "Sincronizando com o Google Drive…" };
  if (st.lastSync) return { icon: "cloudCheck", cls: "drive-ok", text: "Salvo no Google Drive " + timeAgo(st.lastSync) };
  return { icon: "cloud", cls: "drive-ok", text: "Sincronização com o Google Drive ativada" };
}

function icon(name, cls = "") {
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(msg, ms = 3000) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

// Modal genérico. fields: [{name, label, value, type: text|select|check, options}]
function modal({ title, fields = [], ok = "OK", danger = false, body = "" }) {
  return new Promise((resolve) => {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    const inputs = fields.map((f) => {
      if (f.type === "select") {
        const opts = f.options.map((o) => `<option value="${esc(o.value ?? o)}" ${(o.value ?? o) === f.value ? "selected" : ""}>${esc(o.label ?? o)}</option>`).join("");
        return `<label>${esc(f.label)}<select name="${f.name}">${opts}</select></label>`;
      }
      if (f.type === "check") {
        return `<label class="check"><input type="checkbox" name="${f.name}" ${f.value ? "checked" : ""}> ${esc(f.label)}</label>`;
      }
      return `<label>${esc(f.label)}<input type="text" name="${f.name}" value="${esc(f.value || "")}" autocomplete="off"></label>`;
    }).join("");
    bg.innerHTML = `<form class="modal"><h2>${esc(title)}</h2>${body}${inputs}
      <div class="actions"><button type="button" class="btn" data-cancel>Cancelar</button>
      <button type="submit" class="btn ${danger ? "danger" : "primary"}">${esc(ok)}</button></div></form>`;
    const form = bg.querySelector("form");
    const close = (v) => { bg.remove(); resolve(v); };
    bg.addEventListener("mousedown", (e) => { if (e.target === bg) close(null); });
    bg.querySelector("[data-cancel]").onclick = () => close(null);
    form.addEventListener("keydown", (e) => { if (e.key === "Escape") close(null); });
    form.onsubmit = (e) => {
      e.preventDefault();
      const out = {};
      fields.forEach((f) => {
        const el = form.elements[f.name];
        out[f.name] = f.type === "check" ? el.checked : el.value;
      });
      close(out);
    };
    document.body.appendChild(bg);
    const first = form.querySelector("input[type=text], select, button[type=submit]");
    first && first.focus();
    if (first && first.select) first.select();
  });
}

const THUMB_SIZE = 480;

// Renderiza a 1ª página de um PDF (documento do PDF.js ou URL) e salva como miniatura do projeto.
async function saveThumbnail(project, pdfOrUrl) {
  const doc = typeof pdfOrUrl === "string" ? await pdfjsLib.getDocument(pdfOrUrl).promise : pdfOrUrl;
  try {
    const page = await doc.getPage(1);
    const base = page.getViewport({ scale: 1 });
    // lado maior com THUMB_SIZE px: nítido na prévia ampliada, em pé ou deitado
    const vp = page.getViewport({ scale: THUMB_SIZE / Math.max(base.width, base.height) });
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(vp.width);
    canvas.height = Math.round(vp.height);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    await page.render({ canvasContext: ctx, viewport: vp }).promise;
    const blob = await new Promise((res) => canvas.toBlob(res, "image/png"));
    await fetch(`/api/projects/${encodeURIComponent(project)}/thumbnail`, { method: "POST", body: blob, headers: { "Content-Type": "image/png" } });
    return { width: canvas.width, height: canvas.height };
  } finally {
    if (typeof pdfOrUrl === "string") doc.destroy();
  }
}

function timeAgo(ts) {
  const s = (Date.now() / 1000 - ts);
  if (s < 60) return "agora mesmo";
  if (s < 3600) return `há ${Math.floor(s / 60)} min`;
  if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
  if (s < 86400 * 30) return `há ${Math.floor(s / 86400)} dias`;
  return new Date(ts * 1000).toLocaleDateString("pt-BR");
}

// tema salvo por usuário (claro/escuro/sistema)
(function () {
  try {
    const t = localStorage.getItem("theme");
    if (t) document.documentElement.dataset.theme = t;
  } catch (e) { /* sem storage */ }
})();
