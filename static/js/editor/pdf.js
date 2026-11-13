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

// Teto de pixels por página: com zoom alto numa tela de notebook (escala 1,5–2), uma página
// passaria de 30 milhões de pixels. Acima disso a página é desenhada com menos resolução
// e esticada pelo CSS (o mesmo que o visualizador do PDF.js faz).
const MAX_CANVAS_PIXELS = 8e6;

async function renderPage(div, token) {
  if (div.dataset.rendered === String(token)) return;
  div.dataset.rendered = String(token);
  const page = await state.pdf.getPage(+div.dataset.page);
  if (token !== renderToken || !div.isConnected) return;
  const base = page.getViewport({ scale: state.scale });
  const dpr = window.devicePixelRatio || 1;
  const out = Math.min(dpr, Math.sqrt(MAX_CANVAS_PIXELS / (base.width * base.height)));
  const vp = page.getViewport({ scale: state.scale * out });
  const canvas = document.createElement("canvas");
  canvas.width = Math.floor(vp.width);
  canvas.height = Math.floor(vp.height);
  div._task?.cancel();  // um desenho anterior desta página que ainda não terminou
  const task = (div._task = page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }));
  try {
    await task.promise;
  } catch (e) {
    return;  // cancelado por um zoom novo (ou página que não pôde ser desenhada)
  } finally {
    if (div._task === task) div._task = null;
  }
  if (token !== renderToken) return;
  div.querySelector("canvas")?.remove();
  div.prepend(canvas);
  // a camada de texto muda de tamanho com o zoom só pelo CSS (--scale-factor): é criada uma vez
  if (div.querySelector(".textLayer")) return;
  // camada de texto invisível por cima da imagem: permite selecionar e copiar o texto
  const layer = document.createElement("div");
  layer.className = "textLayer";
  layer.style.setProperty("--scale-factor", state.scale);
  try {
    await pdfjsLib.renderTextLayer({
      textContentSource: page.streamTextContent(),
      container: layer,
      viewport: page.getViewport({ scale: state.scale }),
      textDivs: [],
    }).promise;
  } catch (e) { return; /* sem texto selecionável nesta página */ }
  if (div.querySelector(".textLayer")) return;  // outra chamada já pôs a dela
  layer.style.setProperty("--scale-factor", state.scale);  // o zoom pode ter mudado enquanto isso
  div.appendChild(layer);
}

// ------------------------------------------------------------ PDF escuro
function applyPdfDark() { view.classList.toggle("dark", !!store.get("pdfDark", false)); }
applyPdfDark();

// ------------------------------------------------------------ modo apresentação (tela cheia)
// Uma página por vez, do tamanho da tela: setas, espaço, Page Up/Down ou clique avançam e
// voltam; Home/End vão para o começo e o fim; Esc sai.
async function presentPdf() {
  if (!state.pdf) return toast("Compile o projeto primeiro");
  const pdf = state.pdf;
  const total = pdf.numPages;
  let n = currentPage();
  const root = document.createElement("div");
  root.className = "present";
  root.innerHTML = '<canvas></canvas><div class="present-num"></div>';
  document.body.appendChild(root);
  const canvas = root.querySelector("canvas");
  const num = root.querySelector(".present-num");
  let token = 0, numTimer = 0;

  async function show(i) {
    n = Math.max(1, Math.min(total, i));
    const my = ++token;
    const page = await pdf.getPage(n);
    if (my !== token) return;
    const base = page.getViewport({ scale: 1 });
    const scale = Math.min(innerWidth / base.width, innerHeight / base.height);
    const dpr = window.devicePixelRatio || 1;
    const vp = page.getViewport({ scale: scale * dpr });
    const off = document.createElement("canvas");
    off.width = Math.floor(vp.width);
    off.height = Math.floor(vp.height);
    await page.render({ canvasContext: off.getContext("2d"), viewport: vp }).promise;
    if (my !== token) return;
    canvas.width = off.width;
    canvas.height = off.height;
    canvas.getContext("2d").drawImage(off, 0, 0);
    canvas.style.width = Math.floor(base.width * scale) + "px";
    canvas.style.height = Math.floor(base.height * scale) + "px";
    num.textContent = `${n} / ${total}`;
    num.classList.add("on");
    clearTimeout(numTimer);
    numTimer = setTimeout(() => num.classList.remove("on"), 1200);
  }

  const onKey = (e) => {
    const k = e.key;
    if (["ArrowRight", "ArrowDown", "PageDown", " ", "Enter", "n"].includes(k)) show(n + 1);
    else if (["ArrowLeft", "ArrowUp", "PageUp", "Backspace", "p"].includes(k)) show(n - 1);
    else if (k === "Home") show(1);
    else if (k === "End") show(total);
    else if (k === "Escape") exit();
    else return;
    e.preventDefault();
    e.stopPropagation();
  };
  const onResize = () => show(n);
  function exit() {
    removeEventListener("keydown", onKey, true);
    removeEventListener("resize", onResize);
    document.removeEventListener("fullscreenchange", onFs);
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    root.remove();
    goToPage(n);  // volta para o editor na página em que parou
  }
  const onFs = () => { if (!document.fullscreenElement) exit(); };
  root.addEventListener("click", (e) => show(e.clientX < innerWidth / 4 ? n - 1 : n + 1));
  root.addEventListener("contextmenu", (e) => { e.preventDefault(); show(n - 1); });
  addEventListener("keydown", onKey, true);
  addEventListener("resize", onResize);
  try {
    await root.requestFullscreen();
    document.addEventListener("fullscreenchange", onFs);
  } catch (e) { /* sem tela cheia (ex.: bloqueada): apresenta na janela mesmo */ }
  show(n);
}
$("#pdf-present").onclick = presentPdf;

// ------------------------------------------------------------ zoom
// Durante o zoom só o CSS muda: as páginas (com a imagem esticada) e o texto selecionável
// mudam de tamanho na hora, sem desenhar nada. Quando o zoom para, as páginas visíveis são
// redesenhadas nítidas. Antes, cada passo redesenhava as páginas inteiras, e um gesto de
// pinça no touchpad (dezenas de passos por segundo) travava o notebook.
let sharpenTimer = 0;

function setZoom(z, anchor = null) {
  state.zoom = z;
  store.set("pdfZoom", z);
  resizePages(computeScale(), anchor);
}

// anchor: ponto da tela (clientX/Y) que fica parado durante o zoom; sem ele, o centro
function resizePages(scale, anchor = null) {
  if (!state.pdf || !view.querySelector(".pdf-page")) return;
  scale = Math.max(0.25, Math.min(4, scale));
  const old = state.scale;
  if (Math.abs(scale - old) < 1e-4) return;
  const box = view.getBoundingClientRect();
  const ax = anchor ? anchor.x - box.left : view.clientWidth / 2;
  const ay = anchor ? anchor.y - box.top : view.clientHeight / 2;
  // a página sob o ponto e a posição nela (em pontos do PDF), para continuar no mesmo lugar
  const y = view.scrollTop + ay, x = view.scrollLeft + ax;
  const pages = [...view.querySelectorAll(".pdf-page")];
  const pg = pages.find((p) => p.offsetTop + p.offsetHeight >= y) || pages[pages.length - 1];
  const px = (x - pg.offsetLeft) / old, py = (y - pg.offsetTop) / old;

  state.scale = scale;
  zoomLabel();
  // a camada de texto (milhares de trechos invisíveis) some durante o gesto: reescalar a cada
  // passo custava mais que o próprio zoom. Volta, no tamanho novo, em sharpenPages()
  view.classList.add("zooming");
  pages.forEach((d) => {
    const s = state.pageSizes[d.dataset.page - 1];
    d.style.width = Math.floor(s.width * scale) + "px";
    d.style.height = Math.floor(s.height * scale) + "px";
  });
  view.querySelectorAll(".sync-hl").forEach((h) => h.remove());
  paintPdfMatches();
  view.scrollTop = pg.offsetTop + py * scale - ay;
  view.scrollLeft = pg.offsetLeft + px * scale - ax;

  clearTimeout(sharpenTimer);
  sharpenTimer = setTimeout(sharpenPages, 200);
}

// Redesenha na resolução do zoom novo, começando pelas páginas visíveis. As que estão longe
// perdem a imagem antiga (memória) e são desenhadas quando aparecerem.
function sharpenPages() {
  const token = ++renderToken;
  const top = view.scrollTop - view.clientHeight, bottom = view.scrollTop + 2 * view.clientHeight;
  view.querySelectorAll(".pdf-page").forEach((d) => {
    d._task?.cancel();
    d.querySelector(".textLayer")?.style.setProperty("--scale-factor", state.scale);
    if (d.offsetTop + d.offsetHeight < top || d.offsetTop > bottom) d.querySelector("canvas")?.remove();
  });
  view.classList.remove("zooming");
  observer && observer.disconnect();
  observer = new IntersectionObserver((ents) => {
    ents.forEach((en) => { if (en.isIntersecting) renderPage(en.target, token); });
  }, { root: view, rootMargin: "300px 0px" });
  view.querySelectorAll(".pdf-page").forEach((d) => observer.observe(d));
}

$("#zoom-in").onclick = () => setZoom(Math.min(4, +(state.scale * 1.2).toFixed(3)));
$("#zoom-out").onclick = () => setZoom(Math.max(0.25, +(state.scale / 1.2).toFixed(3)));
$("#zoom-fit").onclick = () => setZoom("fit");
view.addEventListener("wheel", (e) => {
  if (!e.ctrlKey) return;
  e.preventDefault();
  // pinça no touchpad: muitos eventos pequenos, zoom proporcional ao movimento;
  // roda do mouse: 10% por clique
  const pinch = e.deltaMode === 0 && Math.abs(e.deltaY) < 50;
  const factor = pinch ? Math.exp(-e.deltaY * 0.01) : e.deltaY < 0 ? 1.1 : 1 / 1.1;
  setZoom(Math.max(0.25, Math.min(4, +(state.scale * factor).toFixed(3))), { x: e.clientX, y: e.clientY });
}, { passive: false });

let resizeTimer;
new ResizeObserver(() => {
  if (state.zoom !== "fit" || !state.pdf) return;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (Math.abs(computeScale() - state.scale) > 0.01) resizePages(computeScale());
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
