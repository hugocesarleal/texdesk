// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Editor, parte 1: estado da página, ícones da barra, CodeMirror e salvamento automático.
// Os arquivos do editor são carregados nesta ordem: completions, core, live, files, compile, pdf,
// pdfsearch, layout, tools, insert, main.

const $ = (s, el = document) => el.querySelector(s);
const PROJECT = decodeURIComponent(location.pathname.split("/").pop());
const P = `/api/projects/${encodeURIComponent(PROJECT)}`;
pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs-3.11.174/pdf.worker.min.js";

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* sem storage */ } },
};

const state = {
  files: [],
  settings: {},
  current: null,          // caminho do arquivo aberto
  docs: {},               // path -> {doc, saved, mtime, timer, saving, gen, conflict}
  tabs: store.get(`tabs:${PROJECT}`, []),  // arquivos abertos em abas
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
$("#btn-search").innerHTML = icon("search");
$("#btn-replace").innerHTML = icon("replace");
$("#ps-toggle-replace").innerHTML = icon("replace");
$("#btn-cite").innerHTML = icon("book") + '<span class="hide-sm">Referência</span>';
$("#btn-help").innerHTML = icon("keyboard");
$("#pdf-present").innerHTML = icon("present");
$("#pdf-search").innerHTML = icon("search");
$("#btn-project-search").innerHTML = icon("search");
$("#ps-close").innerHTML = icon("close");
$("#btn-words").innerHTML = icon("count") + '<span class="hide-sm">Palavras</span>';
$("#btn-history").innerHTML = icon("history") + '<span class="hide-sm">Histórico</span>';
$("#pdf-find-prev").innerHTML = icon("chevronUp");
$("#pdf-find-next").innerHTML = icon("chevron");
$("#pdf-find-close").innerHTML = icon("close");
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
    ? icon("refresh", "spin") + `<span class="hide-xs">${state.refining ? "Atualizando referências…" : "Compilando…"}</span>`
    : icon("refresh") + '<span class="hide-xs">Recompilar</span>';
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
    "Ctrl-H": "replace",
    "Cmd-Alt-F": "replace",
    "Shift-Ctrl-F": false,  // Ctrl+Shift+F é a busca em todos os arquivos
    "Shift-Cmd-F": false,
    "Shift-Ctrl-R": false,
    "Shift-Cmd-Alt-F": false,
    Tab: (c) => (c.somethingSelected() ? c.indentSelection("add") : c.replaceSelection("  ")),
  },
  hintOptions: { hint: latexHint, completeSingle: false },
  phrases: {
    "Search:": "Buscar:",
    "(Use /re/ syntax for regexp search)": "(use /expressão/ para expressão regular)",
    "Replace:": "Substituir:",
    "Replace all:": "Substituir tudo:",
    "With:": "Por:",
    "Replace with:": "Substituir por:",
    "Replace?": "Substituir?",
    "Yes": "Sim",
    "No": "Não",
    "All": "Todas",
    "Stop": "Parar",
    "Jump to line:": "Ir para a linha:",
    "(Use line:column or scroll% syntax)": "(linha:coluna ou porcentagem%)",
  },
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
  if (!d || d.applying || d.typing) return;  // mudança vinda do disco (live.js): não é para salvar
  setSaveState("Editando…");
  $("#tabs .tab.on")?.classList.toggle("dirty", d.doc.getValue() !== d.saved);
  clearTimeout(d.timer);
  d.timer = setTimeout(() => saveDoc(state.current), 700);
  scheduleOutline();
  if (state.settings.autoCompile) scheduleAutoCompile();
});

// ------------------------------------------------------------ salvar
function setSaveState(t) { $("#save-state").textContent = t; }

async function saveDoc(path, force = false) {
  const d = state.docs[path];
  if (!d) return;
  clearTimeout(d.timer);
  finishTyping(d);
  if (d.conflict && !force) return;  // esperando o usuário escolher qual versão fica
  const content = d.doc.getValue();
  if (content === d.saved && !force) { setSaveState("Salvo"); renderTabs(); return; }
  d.saving = (d.saving || 0) + 1;
  try {
    const r = await api(`${P}/file`, { method: "PUT", json: { path, content, mtime: d.mtime, force } });
    d.saved = content;
    d.mtime = r.mtime;
    d.gen = (d.gen || 0) + 1;
    d.conflict = false;
    setSaveState("Salvo");
    if (state.settings.driveSync) setTimeout(pollDrive, 300);
  } catch (e) {
    if (e.data && e.data.conflict) { resolveConflict(path, e.data); return; }
    setSaveState("Erro ao salvar");
    toast("Erro ao salvar: " + e.message);
  } finally {
    d.saving--;
    renderTabs();
  }
}

// O arquivo mudou no disco (outro programa, outra aba, restauração) enquanto havia
// alterações não salvas aqui: o usuário escolhe qual versão fica.
async function resolveConflict(path, disk) {
  const d = state.docs[path];
  if (!d || d.conflict) return;
  d.conflict = true;
  setSaveState("Alterado fora do editor");
  const keepMine = await modal({
    title: "Arquivo alterado fora do editor",
    body: `<p><b>${esc(path)}</b> foi alterado por outro programa (ou em outra aba) enquanto você o editava aqui.</p>
      <p class="muted small">Manter a sua grava por cima da versão do disco, que fica guardada no Histórico. Usar a do disco descarta o que você mudou aqui desde o último salvamento.</p>`,
    ok: "Manter a minha",
    cancel: "Usar a do disco",
    dismissable: false,
  });
  if (!state.docs[path]) return;
  if (keepMine) {
    await saveDoc(path, true);
  } else {
    loadDiskVersion(path, disk.content, disk.mtime);
    d.conflict = false;
    setSaveState("Salvo");
  }
}

// Troca o conteúdo do documento pelo do disco, mantendo cursor e rolagem.
function loadDiskVersion(path, content, mtime) {
  const d = state.docs[path];
  if (!d) return;
  const cursor = d.doc.getCursor();
  const scroll = d.doc === cm.getDoc() ? cm.getScrollInfo() : null;
  d.saved = content;
  d.mtime = mtime;
  d.doc.setValue(content);
  d.doc.setCursor(cursor);
  if (scroll) cm.scrollTo(scroll.left, scroll.top);
  clearTimeout(d.timer);
  renderTabs();
}

async function saveAll() {
  await Promise.all(Object.keys(state.docs).map(saveDoc));
}

window.addEventListener("beforeunload", (e) => {
  finishAllTyping();
  const dirty = Object.values(state.docs).some((d) => d.doc.getValue() !== d.saved);
  if (dirty) { saveAll(); e.preventDefault(); e.returnValue = ""; }
});
