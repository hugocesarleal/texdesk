// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Visualizador de PDF (PDF.js): páginas, zoom, contagem e troca de página, SyncTeX.

// ------------------------------------------------------------ visualizador de PDF (PDF.js)
const view = $("#pdf-view");
let renderToken = 0;
let observer = null;

function zoomLabel() {
  $("#zoom-label").textContent = Math.round(state.scale * 100) + "%";
}

function computeScale() {
  if (state.zoom === "fit") {
    const w = state.pageSizes[0]?.width || 612;
    return Math.max(0.25, (view.clientWidth - 28) / w);
  }
  return state.zoom;
}

async function loadPdf(url) {
  const token = ++renderToken;
  let doc;
  try {
    doc = await pdfjsLib.getDocument({ url, cMapUrl: "/static/vendor/pdfjs-3.11.174/cmaps/", cMapPacked: true }).promise;
  } catch (e) {
    toast("Erro ao abrir PDF: " + e.message);
    return;
  }
  if (token !== renderToken) return;
  const sizes = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const p = await doc.getPage(i);
    const v = p.getViewport({ scale: 1 });
    sizes.push({ width: v.width, height: v.height });
  }
  if (token !== renderToken) return;
  const ratio = view.scrollHeight > view.clientHeight ? view.scrollTop / view.scrollHeight : 0;
  const scrollLeft = view.scrollLeft;
  if (state.pdf && state.pdf !== doc) state.pdf.destroy();
  state.pdf = doc;
  state.pageSizes = sizes;
  $("#page-count").textContent = sizes.length;  // o total aparece já, antes de desenhar as páginas
  await layoutPages(ratio, scrollLeft);
  if (!findBar.hidden) runPdfSearch(true);  // refaz a busca no PDF novo
}

async function layoutPages(scrollRatio = null, scrollLeft = 0) {
  if (!state.pdf) return;
  const token = ++renderToken;
  const scale = computeScale();
  state.scale = scale;
  zoomLabel();
  const container = document.createElement("div");
  container.className = "pdf-pages";
  state.pageSizes.forEach((s, i) => {
    const d = document.createElement("div");
    d.className = "pdf-page";
    d.dataset.page = i + 1;
    d.style.width = Math.floor(s.width * scale) + "px";
    d.style.height = Math.floor(s.height * scale) + "px";
    container.appendChild(d);
  });
  // renderiza fora da tela as páginas que ficarão visíveis, depois troca (sem piscar)
  const ghost = document.createElement("div");
  ghost.style.cssText = "position:absolute;visibility:hidden;left:0;top:0;width:100%;";
  ghost.appendChild(container);
  view.appendChild(ghost);
  const targetTop = scrollRatio !== null ? scrollRatio * (container.scrollHeight + 24) : view.scrollTop;
  const visible = [...container.children].filter((d) => d.offsetTop + d.offsetHeight >= targetTop && d.offsetTop <= targetTop + view.clientHeight);
  await Promise.all(visible.slice(0, 4).map((d) => renderPage(d, token)));
  if (token !== renderToken) { ghost.remove(); return; }
  [...view.children].forEach((c) => { if (c !== ghost) c.remove(); });
  ghost.replaceWith(container);
  view.scrollTop = targetTop;
  view.scrollLeft = scrollLeft;

  observer && observer.disconnect();
  observer = new IntersectionObserver((ents) => {
    ents.forEach((en) => { if (en.isIntersecting) renderPage(en.target, token); });
  }, { root: view, rootMargin: "300px 0px" });
  container.querySelectorAll(".pdf-page").forEach((d) => observer.observe(d));
  updatePageNav();
  paintPdfMatches();
}

// ------------------------------------------------------------ contagem e troca de página
const pageInput = $("#page-input");

function currentPage() {
  // a página com mais área visível (no fim do documento a rolagem trava, e uma regra
  // de "topo da tela" nunca chegaria às últimas páginas)
  const top = view.scrollTop, bottom = top + view.clientHeight;
  let best = 1, bestArea = -1;
  for (const p of view.querySelectorAll(".pdf-page")) {
    const visible = Math.min(bottom, p.offsetTop + p.offsetHeight) - Math.max(top, p.offsetTop);
    if (visible > bestArea) { best = +p.dataset.page; bestArea = visible; }
    if (p.offsetTop > bottom) break;
  }
  return best;
}

// página escolhida no campo: continua mostrada até o usuário rolar (com zoom pequeno
// várias páginas cabem na tela e a "mais visível" poderia ser outra)
let pinnedPage = null;

function updatePageNav() {
  const total = state.pageSizes.length;
  $("#page-nav").hidden = !total;
  $("#page-count").textContent = total;
  if (pinnedPage && Math.abs(view.scrollTop - pinnedPage.top) > 2) pinnedPage = null;
  if (document.activeElement !== pageInput) pageInput.value = total ? (pinnedPage ? pinnedPage.n : currentPage()) : "";
}

function goToPage(n) {
  const pg = view.querySelector(`.pdf-page[data-page="${n}"]`);
  if (!pg) return;
  view.scrollTo({ top: pg.offsetTop - 8 });
  pinnedPage = { n, top: view.scrollTop };
}

let pageNavFrame = 0;
view.addEventListener("scroll", () => {
  cancelAnimationFrame(pageNavFrame);
  pageNavFrame = requestAnimationFrame(updatePageNav);
}, { passive: true });

pageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    const n = parseInt(pageInput.value, 10);
    const total = state.pageSizes.length;
    if (!Number.isInteger(n) || n < 1 || n > total) {
      pageInput.classList.add("invalid");
      pageInput.title = `Digite um número de 1 a ${total}`;
      return;
    }
    goToPage(n);
    pageInput.blur();
  } else if (e.key === "Escape") {
    pageInput.blur();
  }
});
pageInput.addEventListener("input", () => { pageInput.classList.remove("invalid"); pageInput.title = "Digite uma página e aperte Enter"; });
pageInput.addEventListener("focus", () => pageInput.select());
pageInput.addEventListener("blur", () => { pageInput.classList.remove("invalid"); updatePageNav(); });

async function renderPage(div, token) {
  if (div.dataset.rendered === String(token)) return;
  div.dataset.rendered = String(token);
  const page = await state.pdf.getPage(+div.dataset.page);
  if (token !== renderToken && div.isConnected === false) return;
  const dpr = window.devicePixelRatio || 1;
  const vp = page.getViewport({ scale: state.scale * dpr });
  const canvas = document.createElement("canvas");
  canvas.width = Math.floor(vp.width);
  canvas.height = Math.floor(vp.height);
  await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
  div.querySelector("canvas")?.remove();
  div.prepend(canvas);
}

function setZoom(z) {
  const ratio = view.scrollHeight ? view.scrollTop / view.scrollHeight : 0;
  state.zoom = z;
  store.set("pdfZoom", z);
  layoutPages(ratio);
}
$("#zoom-in").onclick = () => setZoom(Math.min(4, +(state.scale * 1.2).toFixed(2)));
$("#zoom-out").onclick = () => setZoom(Math.max(0.25, +(state.scale / 1.2).toFixed(2)));
$("#zoom-fit").onclick = () => setZoom("fit");
view.addEventListener("wheel", (e) => {
  if (!e.ctrlKey) return;
  e.preventDefault();
  setZoom(Math.max(0.25, Math.min(4, +(state.scale * (e.deltaY < 0 ? 1.1 : 1 / 1.1)).toFixed(2))));
}, { passive: false });

let resizeTimer;
new ResizeObserver(() => {
  if (state.zoom !== "fit" || !state.pdf) return;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (Math.abs(computeScale() - state.scale) > 0.01) layoutPages(view.scrollTop / view.scrollHeight);
  }, 150);
}).observe(view);

// ------------------------------------------------------------ SyncTeX
view.addEventListener("dblclick", async (e) => {
  const pg = e.target.closest(".pdf-page");
  if (!pg) return;
  const rect = pg.getBoundingClientRect();
  const x = (e.clientX - rect.left) / state.scale;
  const y = (e.clientY - rect.top) / state.scale;
  try {
    const r = await api(`${P}/synctex/code?page=${pg.dataset.page}&x=${x}&y=${y}`);
    if (r.file) goTo(r.file, r.line);
  } catch (err) { toast(err.message); }
});

async function syncToPdf() {
  if (!state.current || !state.pdf) return toast("Compile o projeto primeiro");
  const line = cm.getCursor().line + 1;
  try {
    const boxes = await api(`${P}/synctex/pdf?file=${encodeURIComponent(state.current)}&line=${line}`);
    if (!boxes.length) return toast("Posição não encontrada no PDF");
    setView("pdf");
    openLogs(false);
    const pg = view.querySelector(`.pdf-page[data-page="${boxes[0].page}"]`);
    if (!pg) return;
    view.querySelectorAll(".sync-hl").forEach((h) => h.remove());
    boxes.forEach((b) => {
      const h = document.createElement("div");
      h.className = "sync-hl";
      h.style.left = b.x * state.scale + "px";
      h.style.top = b.y * state.scale + "px";
      h.style.width = Math.max(8, b.w * state.scale) + "px";
      h.style.height = Math.max(8, b.h * state.scale) + "px";
      pg.appendChild(h);
    });
    view.scrollTo({ top: pg.offsetTop + boxes[0].y * state.scale - view.clientHeight / 3, behavior: "smooth" });
  } catch (err) { toast(err.message); }
}
$("#sync-to-pdf").onclick = syncToPdf;
$("#sync-to-code").onclick = async () => {
  if (!state.pdf) return toast("Compile o projeto primeiro");
  // usa o ponto no topo/centro da área visível do PDF
  const pages = [...view.querySelectorAll(".pdf-page")];
  const mid = view.scrollTop + view.clientHeight / 3;
  const pg = pages.find((p) => p.offsetTop + p.offsetHeight >= mid) || pages[0];
  const y = (mid - pg.offsetTop) / state.scale;
  const x = (pg.offsetWidth / 2) / state.scale;
  const r = await api(`${P}/synctex/code?page=${pg.dataset.page}&x=${x}&y=${y}`);
  if (r.file) goTo(r.file, r.line);
};
