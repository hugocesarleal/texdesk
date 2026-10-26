// Editor do TexDesk: árvore de arquivos, CodeMirror, compilação, PDF.js e SyncTeX.

const $ = (s, el = document) => el.querySelector(s);
const PROJECT = decodeURIComponent(location.pathname.split("/").pop());
const P = `/api/projects/${encodeURIComponent(PROJECT)}`;
pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* sem storage */ } },
};

const state = {
  files: [],
  settings: {},
  current: null,          // caminho do arquivo aberto
  docs: {},               // path -> {doc, saved, timer}
  openFolders: new Set(store.get(`folders:${PROJECT}`, [])),
  selectedFolder: "",
  entries: [],
  compiling: false,
  pendingCompile: false,
  pdf: null,
  pdfUrl: null,
  zoom: store.get("pdfZoom", "fit"),
  scale: 1,
  pageSizes: [],
  firstCompile: true,
};

// ------------------------------------------------------------ ícones da UI
$("#home").innerHTML = '<img src="/static/logo.svg" alt="TexDesk" width="24" height="24">';
$("#toggle-files").innerHTML = icon("menu");
$("#btn-zip").innerHTML = icon("download") + '<span class="hide-sm">.zip</span>';
$("#btn-settings").innerHTML = icon("settings");
$("#new-file").innerHTML = icon("newFile");
$("#new-folder").innerHTML = icon("newFolder");
$("#upload-files").innerHTML = icon("upload");
$("#btn-search").innerHTML = icon("zoomIn").replace("M11 8v6M8 11h6", "");
$("#sync-to-pdf").innerHTML = icon("arrowRight");
$("#sync-to-code").innerHTML = icon("arrowLeft");
$("#btn-compile-menu").innerHTML = icon("chevron");
$("#zoom-in").innerHTML = icon("zoomIn");
$("#zoom-out").innerHTML = icon("zoomOut");
$("#zoom-fit").innerHTML = icon("fit");
$("#btn-download").innerHTML = icon("download");
$("#title").textContent = PROJECT;
document.title = `${PROJECT} — TexDesk`;

function setCompileButton() {
  $("#btn-compile").innerHTML = state.compiling
    ? icon("refresh", "spin") + "Compilando…"
    : icon("refresh") + "Recompilar";
}
setCompileButton();

// ------------------------------------------------------------ CodeMirror
const editorTheme = () => {
  const t = document.documentElement.dataset.theme;
  const dark = t === "dark" || (!t && matchMedia("(prefers-color-scheme: dark)").matches);
  return dark ? "material-darker" : "default";
};

const cm = CodeMirror($("#editor-wrap"), {
  mode: "stex",
  lineNumbers: true,
  lineWrapping: true,
  matchBrackets: true,
  autoCloseBrackets: { pairs: "()[]{}$$", explode: "[]{}" },
  styleActiveLine: true,
  indentUnit: 2,
  tabSize: 2,
  foldGutter: true,
  gutters: ["errors", "CodeMirror-linenumbers", "CodeMirror-foldgutter"],
  theme: editorTheme(),
  extraKeys: {
    "Ctrl-S": () => compile(),
    "Cmd-S": () => compile(),
    "Ctrl-Enter": () => compile(),
    "Cmd-Enter": () => compile(),
    "Ctrl-/": "toggleComment",
    "Cmd-/": "toggleComment",
    "Ctrl-B": () => wrapSelection("\\textbf{", "}"),
    "Ctrl-I": () => wrapSelection("\\textit{", "}"),
    "Ctrl-Space": "autocomplete",
    "Alt-G": "jumpToLine",
    Tab: (c) => (c.somethingSelected() ? c.indentSelection("add") : c.replaceSelection("  ")),
  },
  hintOptions: { hint: latexHint, completeSingle: false },
});
cm.setOption("fontSize", null);
const applyFontSize = () => {
  $("#editor-wrap .CodeMirror").style.fontSize = store.get("fontSize", 14) + "px";
  cm.refresh();
};
applyFontSize();

function wrapSelection(a, b) {
  const sel = cm.getSelection();
  cm.replaceSelection(a + sel + b);
  if (!sel) {
    const c = cm.getCursor();
    cm.setCursor(c.line, c.ch - b.length);
  }
}

cm.on("inputRead", (c, change) => {
  if (change.text[0] === "\\" || /[{,]/.test(change.text[0]) || /^[a-zA-Z]$/.test(change.text[0])) {
    const line = c.getLine(c.getCursor().line).slice(0, c.getCursor().ch);
    if (/\\[a-zA-Z]*$/.test(line) || /\\\w+\*?(\[[^\]]*\])?\{[^{}]*$/.test(line)) {
      c.showHint({ hint: latexHint, completeSingle: false });
    }
  }
});

cm.on("change", () => {
  const d = state.docs[state.current];
  if (!d) return;
  setSaveState("Editando…");
  clearTimeout(d.timer);
  d.timer = setTimeout(() => saveDoc(state.current), 700);
  scheduleOutline();
  if (state.settings.autoCompile) scheduleAutoCompile();
});

// ------------------------------------------------------------ salvar
function setSaveState(t) { $("#save-state").textContent = t; }

async function saveDoc(path) {
  const d = state.docs[path];
  if (!d) return;
  clearTimeout(d.timer);
  const content = d.doc.getValue();
  if (content === d.saved) { setSaveState("Salvo"); return; }
  try {
    await api(`${P}/file`, { method: "PUT", json: { path, content } });
    d.saved = content;
    setSaveState("Salvo");
    if (state.settings.driveSync) setTimeout(pollDrive, 300);
  } catch (e) {
    setSaveState("Erro ao salvar");
    toast("Erro ao salvar: " + e.message);
  }
}

async function saveAll() {
  await Promise.all(Object.keys(state.docs).map(saveDoc));
}

window.addEventListener("beforeunload", (e) => {
  const dirty = Object.values(state.docs).some((d) => d.doc.getValue() !== d.saved);
  if (dirty) { saveAll(); e.preventDefault(); e.returnValue = ""; }
});

// ------------------------------------------------------------ árvore de arquivos
async function loadFiles() {
  state.files = await api(`${P}/files`);
  renderTree();
}

function buildTree() {
  const root = { children: {}, path: "" };
  for (const f of state.files) {
    const parts = f.path.split("/");
    let node = root;
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join("/");
      if (!node.children[part]) node.children[part] = { name: part, path, children: {}, type: "folder" };
      node = node.children[part];
      if (i === parts.length - 1) Object.assign(node, f, { name: part });
    });
  }
  return root;
}

const IMG_EXT = /\.(png|jpe?g|gif|svg|webp|bmp)$/i;

function renderTree() {
  const root = buildTree();
  const html = [];
  const walk = (node, depth) => {
    const kids = Object.values(node.children).sort((a, b) =>
      (a.type === b.type ? a.name.localeCompare(b.name) : a.type === "folder" ? -1 : 1));
    for (const k of kids) {
      const pad = 6 + depth * 14;
      const isMain = k.path === state.settings.main;
      if (k.type === "folder") {
        const open = state.openFolders.has(k.path);
        html.push(`<div class="node ${state.selectedFolder === k.path ? "active" : ""}" data-folder="${esc(k.path)}" style="padding-left:${pad}px">
          ${icon(open ? "chevron" : "chevronRight")}${icon(open ? "folderOpen" : "folder")}<span class="nm">${esc(k.name)}</span>
          <span class="acts"><button class="icon-btn" data-act="rename" title="Renomear">${icon("edit")}</button>
          <button class="icon-btn" data-act="delete" title="Excluir">${icon("trash")}</button></span></div>`);
        if (open) walk(k, depth + 1);
      } else {
        const ic = IMG_EXT.test(k.name) ? "image" : "file";
        html.push(`<div class="node ${state.current === k.path ? "active" : ""}" data-file="${esc(k.path)}" style="padding-left:${pad + 15}px" title="${esc(k.path)}">
          ${icon(ic)}<span class="nm">${esc(k.name)}</span>${isMain ? '<span class="main-badge">principal</span>' : ""}
          <span class="acts">${/\.tex$/.test(k.name) && !isMain ? `<button class="icon-btn" data-act="main" title="Definir como documento principal">${icon("star")}</button>` : ""}
          <button class="icon-btn" data-act="rename" title="Renomear / mover">${icon("edit")}</button>
          <button class="icon-btn" data-act="delete" title="Excluir">${icon("trash")}</button></span></div>`);
      }
    }
  };
  walk(root, 0);
  $("#tree").innerHTML = html.join("") || '<div class="node"><span class="nm">Sem arquivos</span></div>';
}

$("#tree").addEventListener("click", async (e) => {
  const node = e.target.closest(".node");
  if (!node) return;
  const path = node.dataset.file || node.dataset.folder;
  const act = e.target.closest("button[data-act]")?.dataset.act;
  if (act === "delete") {
    const ok = await modal({ title: "Excluir", body: `<p>Excluir <b>${esc(path)}</b>?</p>`, ok: "Excluir", danger: true });
    if (!ok) return;
    await api(`${P}/file?path=${encodeURIComponent(path)}`, { method: "DELETE" });
    Object.keys(state.docs).forEach((p) => { if (p === path || p.startsWith(path + "/")) delete state.docs[p]; });
    if (state.current && (state.current === path || state.current.startsWith(path + "/"))) state.current = null;
    await loadFiles();
    if (!state.current) openFile(state.settings.main);
    return;
  }
  if (act === "rename") {
    const r = await modal({ title: "Renomear / mover", fields: [{ name: "to", label: "Novo caminho", value: path }], ok: "Salvar" });
    if (!r || r.to === path) return;
    try {
      await saveAll();
      await api(`${P}/move`, { json: { from: path, to: r.to } });
      for (const p of Object.keys(state.docs)) {
        if (p === path || p.startsWith(path + "/")) {
          const np = r.to + p.slice(path.length);
          state.docs[np] = state.docs[p];
          delete state.docs[p];
          if (state.current === p) state.current = np;
        }
      }
      state.settings = await api(`${P}/settings`);
      await loadFiles();
      $("#current-file").textContent = state.current || "";
    } catch (err) { toast(err.message); }
    return;
  }
  if (act === "main") {
    state.settings = await api(`${P}/settings`, { json: { main: path } });
    renderTree();
    toast(`Documento principal: ${path}`);
    return;
  }
  if (node.dataset.folder !== undefined) {
    state.openFolders.has(path) ? state.openFolders.delete(path) : state.openFolders.add(path);
    state.selectedFolder = state.selectedFolder === path && !state.openFolders.has(path) ? "" : path;
    store.set(`folders:${PROJECT}`, [...state.openFolders]);
    renderTree();
  } else {
    state.selectedFolder = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
    openFile(path);
    $("#pane-files").classList.remove("mobile-show");
  }
});

$("#new-file").onclick = async () => {
  const base = state.selectedFolder ? state.selectedFolder + "/" : "";
  const r = await modal({ title: "Novo arquivo", fields: [{ name: "path", label: "Caminho", value: base + "novo.tex" }], ok: "Criar" });
  if (!r || !r.path.trim()) return;
  if (state.files.some((f) => f.path === r.path)) return toast("Esse arquivo já existe");
  try {
    await api(`${P}/file`, { method: "PUT", json: { path: r.path, content: "" } });
    await loadFiles();
    openFile(r.path);
  } catch (err) { toast(err.message); }
};

$("#new-folder").onclick = async () => {
  const base = state.selectedFolder ? state.selectedFolder + "/" : "";
  const r = await modal({ title: "Nova pasta", fields: [{ name: "path", label: "Caminho", value: base + "imagens" }], ok: "Criar" });
  if (!r || !r.path.trim()) return;
  try {
    await api(`${P}/folder`, { json: { path: r.path } });
    state.openFolders.add(r.path);
    await loadFiles();
  } catch (err) { toast(err.message); }
};

async function uploadFiles(files, folder = state.selectedFolder) {
  if (!files.length) return;
  const fd = new FormData();
  [...files].forEach((f) => fd.append("files", f));
  fd.append("folder", folder || "");
  try {
    const r = await api(`${P}/upload`, { method: "POST", body: fd });
    toast(`${r.saved.length} arquivo(s) enviado(s)`);
    r.saved.forEach((p) => delete state.docs[p]);
    await loadFiles();
    loadMeta();
  } catch (err) { toast(err.message); }
}
$("#upload-files").onclick = () => $("#upload-input").click();
$("#upload-input").onchange = () => { uploadFiles($("#upload-input").files); $("#upload-input").value = ""; };
const tree = $("#tree");
tree.addEventListener("dragover", (e) => { e.preventDefault(); tree.classList.add("dragover"); });
tree.addEventListener("dragleave", () => tree.classList.remove("dragover"));
tree.addEventListener("drop", (e) => {
  e.preventDefault();
  tree.classList.remove("dragover");
  const folder = e.target.closest(".node[data-folder]")?.dataset.folder ?? state.selectedFolder;
  uploadFiles(e.dataTransfer.files, folder);
});

// ------------------------------------------------------------ abrir arquivos
async function openFile(path) {
  if (!path) return;
  const f = state.files.find((x) => x.path === path);
  if (!f) return;
  if (state.current && state.docs[state.current]) saveDoc(state.current);
  state.current = path;
  $("#current-file").textContent = path;
  renderTree();

  if (!f.text) {
    $("#editor-wrap").hidden = true;
    const pv = $("#preview");
    pv.hidden = false;
    const url = `${P}/file?path=${encodeURIComponent(path)}&raw=1&t=${Date.now()}`;
    if (IMG_EXT.test(path)) pv.innerHTML = `<img src="${url}" alt="${esc(path)}">`;
    else if (/\.pdf$/i.test(path)) pv.innerHTML = `<iframe src="${url}"></iframe>`;
    else pv.innerHTML = `<div class="msg">Arquivo binário (${(f.size / 1024).toFixed(1)} KB)<br><a href="${url}" download>Baixar</a></div>`;
    return;
  }
  $("#preview").hidden = true;
  $("#editor-wrap").hidden = false;
  if (!state.docs[path]) {
    const data = await api(`${P}/file?path=${encodeURIComponent(path)}`);
    const mode = /\.bib$/i.test(path) ? "stex" : /\.(tex|sty|cls|ltx|dtx|bbx|cbx)$/i.test(path) ? "stex" : "text/plain";
    state.docs[path] = { doc: CodeMirror.Doc(data.content, mode), saved: data.content, timer: null };
  }
  if (state.current !== path) return; // trocou de arquivo enquanto carregava
  cm.swapDoc(state.docs[path].doc);
  applyMarkers();
  updateOutline();
  cm.refresh();
  cm.focus();
  store.set(`open:${PROJECT}`, path);
}

async function goTo(file, line) {
  if (file && file !== state.current) {
    if (!state.files.some((f) => f.path === file)) return toast(`Arquivo não está no projeto: ${file}`);
    await openFile(file);
  }
  if (!line) return;
  setView("editor");
  const l = Math.max(0, line - 1);
  cm.setCursor({ line: l, ch: 0 });
  cm.scrollIntoView({ line: l, ch: 0 }, cm.getScrollInfo().clientHeight / 3);
  cm.addLineClass(l, "background", "cm-line-flash");
  setTimeout(() => cm.removeLineClass(l, "background", "cm-line-flash"), 1300);
  cm.focus();
}

// ------------------------------------------------------------ outline (seções)
let outlineTimer;
function scheduleOutline() { clearTimeout(outlineTimer); outlineTimer = setTimeout(updateOutline, 500); }
function updateOutline() {
  const el = $("#outline");
  if (!state.current || !/\.tex$/.test(state.current)) { el.innerHTML = ""; return; }
  const levels = { part: 0, chapter: 1, section: 2, subsection: 3, subsubsection: 4, paragraph: 5, frametitle: 3 };
  const items = [];
  cm.eachLine((lh) => {
    const m = lh.text.match(/^[^%]*?\\(part|chapter|section|subsection|subsubsection|paragraph|frametitle)\*?\s*(?:\[[^\]]*\])?\{([^}]*)/);
    if (m) items.push({ level: levels[m[1]], title: m[2], line: cm.getLineNumber(lh) + 1 });
  });
  if (!items.length) { el.innerHTML = ""; return; }
  const min = Math.min(...items.map((i) => i.level));
  el.innerHTML = "<h4>Estrutura</h4>" + items.map((i) =>
    `<div class="item" data-line="${i.line}" style="padding-left:${10 + (i.level - min) * 12}px">${esc(i.title || "(sem título)")}</div>`).join("");
}
$("#outline").onclick = (e) => { const it = e.target.closest(".item"); if (it) goTo(null, +it.dataset.line); };

// ------------------------------------------------------------ compilação
let autoTimer;
function scheduleAutoCompile() {
  clearTimeout(autoTimer);
  autoTimer = setTimeout(() => compile({ auto: true }), 2000);
}

async function compile(opts = {}) {
  if (state.compiling) { state.pendingCompile = true; return; }
  state.compiling = true;
  setCompileButton();
  if (state.firstCompile && !state.pdf) {
    $("#pdf-empty").innerHTML = "Compilando…<br><small>Na primeira vez o Tectonic baixa os pacotes necessários; pode levar alguns minutos.</small>";
  }
  try {
    await saveAll();
    const r = await api(`${P}/compile`, { json: {} });
    state.firstCompile = false;
    if (r.status === "busy") return;
    state.entries = r.entries || [];
    state.lastLog = r.log || "";
    state.lastOut = r.stdout || "";
    state.lastStatus = r;
    renderLogs();
    applyMarkers();
    if (r.pdf) {
      state.pdfUrl = r.pdf;
      $("#btn-download").href = r.pdf.split("?")[0];
      $("#btn-download").setAttribute("download", PROJECT + ".pdf");
      await loadPdf(r.pdf);
      if (state.pdf) saveThumbnail(PROJECT, state.pdf).catch(() => {});
    } else {
      if (!state.pdf) $("#pdf-empty").innerHTML = "Não foi possível gerar o PDF. Veja os logs.";
      if (!opts.auto) openLogs(true);
    }
    if (r.message) toast(r.message, 5000);
  } catch (e) {
    toast("Erro na compilação: " + e.message, 5000);
  } finally {
    state.compiling = false;
    setCompileButton();
    if (state.pendingCompile) { state.pendingCompile = false; compile(opts); }
  }
}

$("#btn-compile").onclick = () => compile();

$("#btn-compile-menu").onclick = (e) => {
  e.stopPropagation();
  let menu = $(".compile-menu");
  if (menu) { menu.remove(); return; }
  menu = document.createElement("div");
  menu.className = "compile-menu";
  menu.innerHTML = `
    <label><input type="checkbox" data-k="autoCompile" ${state.settings.autoCompile ? "checked" : ""}> Compilação automática</label>
    <label><input type="checkbox" data-k="shellEscape" ${state.settings.shellEscape ? "checked" : ""}> Permitir shell-escape (minted…)</label>`;
  const rect = e.currentTarget.getBoundingClientRect();
  menu.style.left = rect.left + "px";
  menu.style.top = rect.bottom + 4 + "px";
  menu.onclick = (ev) => ev.stopPropagation();
  menu.onchange = async (ev) => {
    state.settings = await api(`${P}/settings`, { json: { [ev.target.dataset.k]: ev.target.checked } });
  };
  document.body.appendChild(menu);
};
document.addEventListener("click", () => $(".compile-menu")?.remove());

// ------------------------------------------------------------ logs
function counts() {
  const c = { error: 0, warning: 0, typesetting: 0 };
  state.entries.forEach((e) => { c[e.level] = (c[e.level] || 0) + 1; });
  return c;
}

let logFilter = "all";
function renderLogs() {
  const c = counts();
  $("#btn-logs").innerHTML = icon("logs") + "Logs" +
    (c.error ? ` <span class="badge err">${c.error}</span>` : "") +
    (c.warning ? ` <span class="badge warn">${c.warning}</span>` : "");
  const list = state.entries.filter((e) => logFilter === "all" || e.level === logFilter);
  const s = state.lastStatus || {};
  const summary = s.status === "success" ? `Compilado em ${s.time}s` : s.status ? `Compilação com problemas (${s.time ?? "?"}s)` : "Ainda não compilado";
  const label = { error: "Erro", warning: "Aviso", typesetting: "Diagramação" };
  $("#logs").innerHTML = `
    <div class="log-filter">
      <span class="log-summary">${esc(summary)}</span>
      ${["all", "error", "warning", "typesetting"].map((f) =>
        `<button class="btn small ${logFilter === f ? "primary" : ""}" data-filter="${f}">${{ all: "Todos", error: `Erros (${c.error})`, warning: `Avisos (${c.warning})`, typesetting: `Caixas (${c.typesetting})` }[f]}</button>`).join("")}
      <button class="btn small" data-close>Fechar</button>
    </div>
    ${list.length ? "" : `<p style="color:var(--muted)">${state.entries.length ? "Nada neste filtro." : "Nenhuma mensagem. 🎉"}</p>`}
    ${list.map((e, i) => `<div class="log-entry ${e.level}" data-i="${state.entries.indexOf(e)}">
      <div class="hd"><span class="msg">${esc(label[e.level] || e.level)}: ${esc(e.message)}</span>
      <span class="loc">${esc(e.file || "")}${e.line ? ":" + e.line : ""}</span></div>
      ${e.content ? `<pre>${esc(e.content)}</pre>` : ""}</div>`).join("")}
    <details class="log-raw"><summary>Log bruto (.log)</summary><pre>${esc(state.lastLog || "")}</pre></details>
    <details class="log-raw"><summary>Saída do compilador</summary><pre>${esc(state.lastOut || "")}</pre></details>`;
}

$("#logs").onclick = (e) => {
  const f = e.target.closest("[data-filter]");
  if (f) { logFilter = f.dataset.filter; renderLogs(); return; }
  if (e.target.closest("[data-close]")) { openLogs(false); return; }
  const en = e.target.closest(".log-entry");
  if (en) {
    const entry = state.entries[+en.dataset.i];
    if (entry.file && !entry.external) goTo(entry.file, entry.line);
  }
};

function openLogs(open) {
  $("#logs").classList.toggle("open", open);
  if (open) setView("pdf");
}
$("#btn-logs").onclick = () => openLogs(!$("#logs").classList.contains("open"));
renderLogs();

function applyMarkers() {
  cm.clearGutter("errors");
  for (let i = 0; i < cm.lineCount(); i++) {
    cm.removeLineClass(i, "background", "cm-line-error");
    cm.removeLineClass(i, "background", "cm-line-warning");
  }
  if (!state.current) return;
  for (const e of state.entries) {
    if (e.file !== state.current || !e.line || e.level === "typesetting") continue;
    const l = e.line - 1;
    if (l >= cm.lineCount()) continue;
    const m = document.createElement("div");
    m.className = e.level === "error" ? "gutter-err" : "gutter-warn";
    m.title = e.message;
    const info = cm.lineInfo(l);
    if (!(info.gutterMarkers && info.gutterMarkers.errors && info.gutterMarkers.errors.className === "gutter-err")) {
      cm.setGutterMarker(l, "errors", m);
    }
    cm.addLineClass(l, "background", e.level === "error" ? "cm-line-error" : "cm-line-warning");
  }
}

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
    doc = await pdfjsLib.getDocument({ url, cMapUrl: "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/cmaps/", cMapPacked: true }).promise;
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
  await layoutPages(ratio, scrollLeft);
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
}

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
  if (!state.current || !state.pdf) return toast("Compile primeiro");
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
  if (!state.pdf) return toast("Compile primeiro");
  // usa o ponto no topo/centro da área visível do PDF
  const pages = [...view.querySelectorAll(".pdf-page")];
  const mid = view.scrollTop + view.clientHeight / 3;
  const pg = pages.find((p) => p.offsetTop + p.offsetHeight >= mid) || pages[0];
  const y = (mid - pg.offsetTop) / state.scale;
  const x = (pg.offsetWidth / 2) / state.scale;
  const r = await api(`${P}/synctex/code?page=${pg.dataset.page}&x=${x}&y=${y}`);
  if (r.file) goTo(r.file, r.line);
};

// ------------------------------------------------------------ divisores redimensionáveis
function makeSplitter(el, onMove) {
  el.addEventListener("mousedown", (e) => {
    if (e.target.closest("button")) return;
    e.preventDefault();
    el.classList.add("drag");
    document.body.style.cursor = "col-resize";
    const shield = document.createElement("div");
    shield.style.cssText = "position:fixed;inset:0;z-index:999;cursor:col-resize";
    document.body.appendChild(shield);
    const move = (ev) => onMove(ev.clientX);
    const up = () => {
      el.classList.remove("drag");
      document.body.style.cursor = "";
      shield.remove();
      removeEventListener("mousemove", move);
      removeEventListener("mouseup", up);
      cm.refresh();
    };
    addEventListener("mousemove", move);
    addEventListener("mouseup", up);
  });
}
const filesPane = $("#pane-files");
const editorPane = $("#pane-editor");
const pdfPane = $("#pane-pdf");
filesPane.style.width = store.get("filesWidth", 240) + "px";
const editorFrac = store.get("editorFrac", 0.5);
editorPane.style.flex = `${editorFrac} 1 0`;
pdfPane.style.flex = `${1 - editorFrac} 1 0`;
makeSplitter($("#split-1"), (x) => {
  const w = Math.max(140, Math.min(500, x));
  filesPane.style.width = w + "px";
  store.set("filesWidth", w);
});
makeSplitter($("#split-2"), (x) => {
  const left = editorPane.getBoundingClientRect().left;
  const total = editorPane.offsetWidth + pdfPane.offsetWidth;
  const frac = Math.max(0.15, Math.min(0.85, (x - left) / total));
  editorPane.style.flex = `${frac} 1 0`;
  pdfPane.style.flex = `${1 - frac} 1 0`;
  store.set("editorFrac", frac);
});

// ------------------------------------------------------------ mobile / painéis
function setView(v) {
  $("#ide").dataset.view = v;
  document.querySelectorAll(".mobile-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  if (v === "editor") setTimeout(() => cm.refresh(), 0);
}
document.querySelectorAll(".mobile-tabs button").forEach((b) => (b.onclick = () => setView(b.dataset.view)));
$("#toggle-files").onclick = () => {
  if (matchMedia("(max-width: 820px)").matches) filesPane.classList.toggle("mobile-show");
  else {
    const hidden = filesPane.style.display === "none";
    filesPane.style.display = hidden ? "" : "none";
    $("#split-1").style.display = hidden ? "" : "none";
    cm.refresh();
  }
};

// ------------------------------------------------------------ outros botões
$("#btn-zip").onclick = async () => { await saveAll(); location.href = `${P}/zip`; };
$("#btn-search").onclick = () => cm.execCommand("find");

$("#btn-settings").onclick = async () => {
  const texs = state.files.filter((f) => /\.tex$/.test(f.path)).map((f) => f.path);
  const r = await modal({
    title: "Configurações",
    fields: [
      { name: "main", label: "Documento principal", type: "select", value: state.settings.main, options: texs.length ? texs : [state.settings.main] },
      { name: "theme", label: "Tema", type: "select", value: document.documentElement.dataset.theme || "", options: [{ value: "", label: "Sistema" }, { value: "light", label: "Claro" }, { value: "dark", label: "Escuro" }] },
      { name: "fontSize", label: "Tamanho da fonte do editor", type: "select", value: String(store.get("fontSize", 14)), options: ["12", "13", "14", "15", "16", "18", "20"] },
      { name: "autoCompile", label: "Compilação automática", type: "check", value: state.settings.autoCompile },
      { name: "shellEscape", label: "Permitir shell-escape (necessário p/ minted)", type: "check", value: state.settings.shellEscape },
      { name: "driveSync", label: "Sincronizar este projeto com o Google Drive", type: "check", value: state.settings.driveSync },
    ],
    ok: "Salvar",
  });
  if (!r) return;
  state.settings = await api(`${P}/settings`, { json: { main: r.main, autoCompile: r.autoCompile, shellEscape: r.shellEscape, driveSync: r.driveSync } });
  if (r.driveSync) {
    const ds = await api("/api/drive/status").catch(() => ({}));
    if (!ds.connected) toast("Conecte o Google Drive no painel de projetos para a sincronização começar.", 6000);
  }
  pollDrive();
  if (r.theme) document.documentElement.dataset.theme = r.theme; else delete document.documentElement.dataset.theme;
  try { r.theme ? localStorage.setItem("theme", r.theme) : localStorage.removeItem("theme"); } catch (e) { /* sem storage */ }
  cm.setOption("theme", editorTheme());
  store.set("fontSize", +r.fontSize);
  applyFontSize();
  renderTree();
};

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
