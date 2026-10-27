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
    const inside = (p) => p === path || p.startsWith(path + "/");
    Object.keys(state.docs).forEach((p) => { if (inside(p)) delete state.docs[p]; });
    state.tabs = state.tabs.filter((p) => !inside(p));
    if (state.current && inside(state.current)) state.current = null;
    await loadFiles();
    if (!state.current) openFile(state.tabs[state.tabs.length - 1] || state.settings.main);
    else renderTabs();
    return;
  }
  if (act === "rename") {
    const r = await modal({ title: "Renomear / mover", fields: [{ name: "to", label: "Novo caminho", value: path }], ok: "Salvar" });
    if (!r || r.to === path) return;
    try {
      await saveAll();
      await api(`${P}/move`, { json: { from: path, to: r.to } });
      const moved = (p) => (p === path || p.startsWith(path + "/") ? r.to + p.slice(path.length) : p);
      for (const p of Object.keys(state.docs)) {
        const np = moved(p);
        if (np === p) continue;
        state.docs[np] = state.docs[p];
        delete state.docs[p];
        state.docs[np].mtime = null;  // o arquivo movido é outro no disco: não confere conflito
      }
      state.current = state.current && moved(state.current);
      state.tabs = state.tabs.map(moved);
      state.settings = await api(`${P}/settings`);
      await loadFiles();
      renderTabs();
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
  if (!state.tabs.includes(path)) state.tabs.push(path);
  renderTabs();
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
    state.docs[path] = { doc: CodeMirror.Doc(data.content, mode), saved: data.content, mtime: data.mtime, timer: null, saving: 0, gen: 0 };
  }
  if (state.current !== path) return; // trocou de arquivo enquanto carregava
  cm.swapDoc(state.docs[path].doc);
  applyMarkers();
  updateOutline();
  cm.refresh();
  cm.focus();
  store.set(`open:${PROJECT}`, path);
}

// ------------------------------------------------------------ abas
const isDirty = (p) => { const d = state.docs[p]; return !!d && d.doc.getValue() !== d.saved; };

function renderTabs() {
  const el = $("#tabs");
  if (state.files.length) state.tabs = state.tabs.filter((p) => state.files.some((f) => f.path === p));
  const base = (p) => p.split("/").pop();
  el.innerHTML = state.tabs.map((p) => {
    const same = state.tabs.filter((q) => base(q) === base(p)).length > 1;  // nomes iguais: mostra a pasta
    const on = p === state.current;
    return `<div class="tab ${on ? "on" : ""} ${isDirty(p) ? "dirty" : ""}" data-path="${esc(p)}" title="${esc(p)}" role="tab" aria-selected="${on}">
      <span class="nm">${esc(same ? p : base(p))}</span>
      <button class="x" data-close title="Fechar aba (clique do meio)" aria-label="Fechar ${esc(base(p))}">${icon("close")}</button></div>`;
  }).join("");
  store.set(`tabs:${PROJECT}`, state.tabs);
  const on = el.querySelector(".tab.on");  // mantém a aba atual visível
  if (on) {
    const l = on.offsetLeft, r = l + on.offsetWidth;
    if (l < el.scrollLeft) el.scrollLeft = l - 8;
    else if (r > el.scrollLeft + el.clientWidth) el.scrollLeft = r - el.clientWidth + 8;
  }
}

async function closeTab(path) {
  const i = state.tabs.indexOf(path);
  if (i < 0) return;
  if (state.docs[path]) {
    await saveDoc(path);
    if (isDirty(path)) return toast("Não foi possível salvar este arquivo; a aba continua aberta.");
    delete state.docs[path];
  }
  state.tabs.splice(i, 1);
  if (state.current === path) {
    state.current = null;
    await openFile(state.tabs[Math.min(i, state.tabs.length - 1)] || state.settings.main);
  } else renderTabs();
}

$("#tabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (!tab) return;
  if (e.target.closest("[data-close]")) closeTab(tab.dataset.path);
  else if (tab.dataset.path !== state.current) openFile(tab.dataset.path);
});
$("#tabs").addEventListener("mousedown", (e) => { if (e.button === 1) e.preventDefault(); });  // sem rolagem automática
$("#tabs").addEventListener("auxclick", (e) => {
  const tab = e.target.closest(".tab");
  if (e.button === 1 && tab) closeTab(tab.dataset.path);
});
$("#tabs").addEventListener("wheel", (e) => {
  if (!e.deltaY || e.shiftKey) return;
  $("#tabs").scrollLeft += e.deltaY;
  e.preventDefault();
}, { passive: false });

// ------------------------------------------------------------ mudanças feitas fora do editor
// Confere de tempos em tempos (e ao voltar para a janela) se algum arquivo aberto mudou no
// disco. Sem alterações pendentes aqui, recarrega sozinho; com alterações, pergunta.
let externalBusy = false;
async function checkExternalChanges() {
  if (externalBusy || document.hidden || !state.files.length) return;
  externalBusy = true;
  try {
    const gens = Object.fromEntries(Object.entries(state.docs).map(([p, d]) => [p, d.gen]));
    let files;
    try { files = await api(`${P}/files`); } catch (e) { return; }
    const shape = (fs) => fs.map((f) => f.path + "|" + f.type).join("\n");
    const treeChanged = shape(files) !== shape(state.files);
    state.files = files;
    if (treeChanged) { renderTree(); renderTabs(); }
    for (const [path, d] of Object.entries(state.docs)) {
      if (d.saving || d.gen !== gens[path] || d.conflict || !d.mtime) continue;
      const f = files.find((x) => x.path === path);
      if (!f) continue;  // apagado fora: se houver alterações, o próximo salvamento recria o arquivo
      if (Math.abs(f.mtime - d.mtime) <= 0.001) continue;
      let disk;
      try { disk = await api(`${P}/file?path=${encodeURIComponent(path)}`); } catch (e) { continue; }
      if (state.docs[path] !== d || d.saving || d.gen !== gens[path]) continue;
      if (isDirty(path)) resolveConflict(path, disk);
      else if (disk.content !== d.saved) {
        loadDiskVersion(path, disk.content, disk.mtime);
        toast(`${path} foi alterado fora do editor e foi recarregado.`, 4000);
      } else d.mtime = disk.mtime;
    }
  } finally { externalBusy = false; }
}
setInterval(checkExternalChanges, 4000);
addEventListener("focus", checkExternalChanges);
document.addEventListener("visibilitychange", checkExternalChanges);

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
