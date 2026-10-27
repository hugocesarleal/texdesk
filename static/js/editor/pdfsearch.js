// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Busca de palavras no PDF compilado: ignora maiúsculas e acentos, destaca as ocorrências
// nas páginas e navega entre elas (Enter / Shift+Enter).

const findBar = $("#pdf-find");
const findInput = $("#pdf-find-input");
const pdfFind = { text: null, matches: [], current: -1, token: 0, pending: false };

// "Ação" → "acao": uma letra vira uma letra (ou nenhuma), para mapear de volta à posição no PDF
const fold = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

// Texto de cada página, com a posição de cada caractere (em pontos, escala 1)
async function pdfPagesText() {
  const doc = state.pdf;
  if (pdfFind.text && pdfFind.text.doc === doc) return pdfFind.text.pages;
  const pages = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const vp = page.getViewport({ scale: 1 });
    const content = await page.getTextContent();
    let norm = "";
    const map = [];  // índice em norm -> [item, caractere] (null para espaços inseridos)
    const items = [];
    const space = () => { if (norm && norm[norm.length - 1] !== " ") { norm += " "; map.push(null); } };
    for (const it of content.items) {
      if (!it.str) { if (it.hasEOL) space(); continue; }
      const t = pdfjsLib.Util.transform(vp.transform, it.transform);
      const h = Math.hypot(t[2], t[3]);
      const idx = items.push({ x: t[4], y: t[5], h, cw: it.width / it.str.length }) - 1;
      [...it.str].forEach((c, k) => {
        const f = /\s/.test(c) ? " " : fold(c);
        for (const ch of f) {
          if (ch === " " && norm[norm.length - 1] === " ") continue;
          norm += ch;
          map.push(ch === " " ? null : [idx, k]);
        }
      });
      if (it.hasEOL) space();
    }
    pages.push({ norm, map, items });
  }
  if (doc !== state.pdf) return [];
  pdfFind.text = { doc, pages };
  return pages;
}

// Retângulos de uma ocorrência: um por trecho contínuo de cada item de texto
function matchRects(pg, start, end) {
  const rects = [];
  let cur = null;
  for (let i = start; i < end; i++) {
    const m = pg.map[i];
    if (!m) continue;
    const [idx, k] = m;
    if (cur && cur.idx === idx && k === cur.k2 + 1) { cur.k2 = k; continue; }
    cur = { idx, k1: k, k2: k };
    rects.push(cur);
  }
  return rects.map(({ idx, k1, k2 }) => {
    const it = pg.items[idx];
    return { x: it.x + k1 * it.cw, y: it.y - it.h * 0.88, w: (k2 - k1 + 1) * it.cw, h: it.h * 1.12 };
  });
}

async function runPdfSearch(keepPosition = false) {
  const token = ++pdfFind.token;
  pdfFind.pending = false;
  const q = fold(findInput.value).replace(/\s+/g, " ").trim();
  const before = pdfFind.matches[pdfFind.current];
  pdfFind.matches = [];
  pdfFind.current = -1;
  if (!q || !state.pdf) { paintPdfMatches(); updateFindCount(); return; }
  $("#pdf-find-count").textContent = "Buscando…";
  const pages = await pdfPagesText();
  if (token !== pdfFind.token) return;
  pages.forEach((pg, p) => {
    for (let i = pg.norm.indexOf(q); i !== -1; i = pg.norm.indexOf(q, i + q.length)) {
      pdfFind.matches.push({ page: p + 1, rects: matchRects(pg, i, i + q.length) });
    }
  });
  if (pdfFind.matches.length) {
    // depois de recompilar, fica perto de onde estava; numa busca nova, começa na página visível
    const from = keepPosition && before ? before.page : currentPage();
    const i = pdfFind.matches.findIndex((m) => m.page >= from);
    pdfFind.current = i === -1 ? 0 : i;
  }
  paintPdfMatches();
  updateFindCount();
  if (!keepPosition) scrollToMatch();
}

function updateFindCount() {
  const n = pdfFind.matches.length;
  const el = $("#pdf-find-count");
  el.textContent = !findInput.value.trim() ? "" : n ? `${pdfFind.current + 1} de ${n}` : "Nada encontrado";
  findBar.classList.toggle("none", !!findInput.value.trim() && !n);
}

// chamado também depois de redesenhar as páginas (zoom, recompilação)
function paintPdfMatches() {
  view.querySelectorAll(".find-hl").forEach((h) => h.remove());
  if (findBar.hidden) return;
  pdfFind.matches.forEach((m, i) => {
    const pg = view.querySelector(`.pdf-page[data-page="${m.page}"]`);
    if (!pg) return;
    m.rects.forEach((r) => {
      const h = document.createElement("div");
      h.className = "find-hl" + (i === pdfFind.current ? " current" : "");
      h.style.left = r.x * state.scale + "px";
      h.style.top = r.y * state.scale + "px";
      h.style.width = Math.max(4, r.w * state.scale) + "px";
      h.style.height = Math.max(6, r.h * state.scale) + "px";
      pg.appendChild(h);
    });
  });
}

function scrollToMatch() {
  const m = pdfFind.matches[pdfFind.current];
  if (!m) return;
  const pg = view.querySelector(`.pdf-page[data-page="${m.page}"]`);
  if (!pg) return;
  const r = m.rects[0];
  view.scrollTo({ top: pg.offsetTop + r.y * state.scale - view.clientHeight / 3 });
  const left = r.x * state.scale;
  if (left < view.scrollLeft || left > view.scrollLeft + view.clientWidth - 40) view.scrollLeft = Math.max(0, left - 40);
}

function stepMatch(dir) {
  const n = pdfFind.matches.length;
  if (!n) return;
  pdfFind.current = (pdfFind.current + dir + n) % n;
  paintPdfMatches();
  updateFindCount();
  scrollToMatch();
}

function openPdfSearch() {
  if (!state.pdf) return toast("Compile primeiro");
  setView("pdf");
  openLogs(false);
  findBar.hidden = false;
  const sel = String(getSelection() || "").trim();
  if (sel && sel.length < 80 && !sel.includes("\n") && !cm.hasFocus()) findInput.value = sel;
  findInput.focus();
  findInput.select();
  if (findInput.value.trim()) runPdfSearch();
}

function closePdfSearch() {
  findBar.hidden = true;
  pdfFind.token++;
  paintPdfMatches();
}

let findTimer;
findInput.addEventListener("input", () => {
  pdfFind.pending = true;
  clearTimeout(findTimer);
  findTimer = setTimeout(runPdfSearch, 200);
});
findInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    clearTimeout(findTimer);
    // Enter logo depois de digitar: busca o texto novo em vez de pular no resultado antigo
    if (pdfFind.pending) runPdfSearch();
    else stepMatch(e.shiftKey ? -1 : 1);
  } else if (e.key === "Escape") {
    e.preventDefault();
    closePdfSearch();
  }
});
$("#pdf-find-prev").onclick = () => stepMatch(-1);
$("#pdf-find-next").onclick = () => stepMatch(1);
$("#pdf-find-close").onclick = closePdfSearch;
$("#pdf-search").onclick = () => (findBar.hidden ? openPdfSearch() : closePdfSearch());

// Ctrl+F no PDF busca no PDF (no editor continua buscando no código)
let lastPane = "editor";
document.addEventListener("pointerdown", (e) => { lastPane = e.target.closest("#pane-pdf") ? "pdf" : "other"; }, true);
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "f" && !cm.hasFocus()
      && (lastPane === "pdf" || findBar.contains(document.activeElement))) {
    e.preventDefault();
    openPdfSearch();
  }
});

// Palavras do PDF (para a contagem de palavras)
async function pdfWordCount() {
  if (!state.pdf) return null;
  const pages = await pdfPagesText();
  return pages.reduce((n, pg) => n + (pg.norm.match(/[\p{L}\p{N}]+(?:[-'’][\p{L}\p{N}]+)*/gu) || []).length, 0);
}
