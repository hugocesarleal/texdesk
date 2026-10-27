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

$("#btn-settings").onclick = async () => {
  const texs = state.files.filter((f) => /\.tex$/.test(f.path)).map((f) => f.path);
  const r = await modal({
    title: "Configurações",
    fields: [
      { name: "main", label: "Documento principal", type: "select", value: state.settings.main, options: texs.length ? texs : [state.settings.main] },
      { name: "theme", label: "Tema", type: "select", value: document.documentElement.dataset.theme || "", options: [{ value: "", label: "Sistema" }, { value: "light", label: "Claro" }, { value: "dark", label: "Escuro" }] },
      { name: "fontSize", label: "Tamanho da fonte do editor", type: "select", value: String(store.get("fontSize", 14)), options: ["12", "13", "14", "15", "16", "18", "20"] },
      { name: "spell", label: "Corretor ortográfico", type: "select", value: spellLang(), options: SPELL_LANGS },
      { name: "autoCompile", label: "Compilação automática", type: "check", value: state.settings.autoCompile },
      { name: "shellEscape", label: "Permitir shell-escape (necessário para o pacote minted)", type: "check", value: state.settings.shellEscape },
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
  if (r.spell !== spellLang()) store.set(`spell:${PROJECT}`, r.spell);  // só grava se mudou o automático
  applySpellcheck();
  renderTree();
};
