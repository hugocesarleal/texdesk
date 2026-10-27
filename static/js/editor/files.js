// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Árvore de arquivos (criar, renomear, mover, enviar), abrir arquivos e estrutura de seções.

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
