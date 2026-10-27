// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Editor, parte 1: estado da página, ícones da barra, CodeMirror e salvamento automático.
// Os arquivos do editor são carregados nesta ordem: core, files, compile, pdf, layout, main.

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
