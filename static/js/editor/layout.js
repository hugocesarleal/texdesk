// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Divisores redimensionáveis, layout de celular, botões da barra e configurações.

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
$("#btn-replace").onclick = () => cm.execCommand("replace");

// ------------------------------------------------------------ atalhos de teclado
const MOD = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";
const SHORTCUTS = [
  ["Geral", [["Salvar e compilar", [`${MOD}+S`, `${MOD}+Enter`]]]],
  ["Editor", [
    ["Buscar no arquivo", [`${MOD}+F`]],
    ["Buscar e substituir no arquivo", [`${MOD}+H`]],
    ["Próxima / anterior ocorrência", [`${MOD}+G`, `Shift+${MOD}+G`]],
    ["Ir para a linha", ["Alt+G"]],
    ["Negrito / itálico", [`${MOD}+B`, `${MOD}+I`]],
    ["Comentar / descomentar linhas", [`${MOD}+/`]],
    ["Sugestões de comandos", [`${MOD}+Espaço`]],
    ["Desfazer / refazer", [`${MOD}+Z`, `${MOD}+Y`]],
    ["Colar imagem como figura", [`${MOD}+V`]],
  ]],
  ["Projeto", [
    ["Buscar e substituir em todos os arquivos", [`${MOD}+Shift+F`]],
    ["Fechar aba", ["Clique do meio na aba"]],
    ["Esta lista de atalhos", ["F1", "?"]],
  ]],
  ["PDF", [
    ["Buscar no PDF (com o PDF selecionado)", [`${MOD}+F`]],
    ["Ir do PDF para o código", ["Clique duplo no PDF"]],
    ["Zoom", [`${MOD}+roda do mouse`]],
    ["Apresentação: avançar / voltar", ["→", "←", "Espaço"]],
    ["Sair da apresentação", ["Esc"]],
  ]],
];
function openShortcuts() {
  if (document.querySelector(".modal.keys")) return;
  panel({
    title: "Atalhos de teclado",
    cls: "keys",
    body: SHORTCUTS.map(([group, rows]) => `<h3 class="modal-sec">${esc(group)}</h3><table class="keys-table">
      ${rows.map(([what, keys]) => `<tr><td>${esc(what)}</td><td>${keys.map((k) => `<kbd>${esc(k)}</kbd>`).join(" ")}</td></tr>`).join("")}</table>`).join(""),
  });
}
$("#btn-help").onclick = openShortcuts;
addEventListener("keydown", (e) => {
  const typing = e.target.closest("input, textarea, select, [contenteditable], .CodeMirror");
  if (e.key === "F1" || (e.key === "?" && !typing && !e.ctrlKey && !e.metaKey)) {
    e.preventDefault();
    openShortcuts();
  }
});

$("#btn-settings").onclick = async () => {
  const dlg = modal({
    title: "Configurações",
    cls: "settings",
    fields: [
      { type: "heading", label: "Este projeto" },
      { name: "spell", label: "Idioma do corretor ortográfico", type: "select", value: spellLang(), options: SPELL_LANGS },
      { name: "autoCompile", label: "Compilar sozinho enquanto edito", type: "check", value: state.settings.autoCompile },
      { name: "shellEscape", label: "Permitir shell-escape (necessário para o pacote minted)", type: "check", value: state.settings.shellEscape },
      { name: "driveSync", label: "Sincronizar com o Google Drive", type: "check", value: state.settings.driveSync },
      { type: "heading", label: "Editor (todos os projetos)" },
      { name: "theme", label: "Tema", type: "select", value: document.documentElement.dataset.theme || "", options: [{ value: "", label: "Igual ao sistema" }, { value: "light", label: "Claro" }, { value: "dark", label: "Escuro" }] },
      { name: "fontSize", label: "Tamanho da fonte do editor", type: "select", value: String(store.get("fontSize", 14)), options: ["12", "13", "14", "15", "16", "18", "20"] },
      { name: "pdfDark", label: "PDF com fundo escuro (inverte as cores das páginas na tela)", type: "check", value: store.get("pdfDark", false) },
      { type: "html", html: '<div class="set-row"><span>Dicionário pessoal do corretor</span><button type="button" class="btn small" id="set-dict">Ver palavras</button></div>' },
    ],
    ok: "Salvar",
  });
  $("#set-dict").onclick = openPersonalDict;
  const r = await dlg;
  if (!r) return;
  store.set("pdfDark", r.pdfDark);
  applyPdfDark();
  state.settings = await api(`${P}/settings`, { json: { autoCompile: r.autoCompile, shellEscape: r.shellEscape, driveSync: r.driveSync } });
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
  if (r.spell !== spellLang()) store.set(`spell:${PROJECT}`, r.spell);  // só grava se mudou o automático
  applySpellcheck();
  renderTree();
};
