// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Ferramentas do editor: busca e substituição em todos os arquivos, contagem de palavras,
// histórico de versões e corretor ortográfico.

// ------------------------------------------------------------ busca em todos os arquivos
const psearch = $("#psearch");
const psInput = $("#ps-input");
const psOpts = { case: false, word: false, regex: false };
let psToken = 0;
// pouco texto antes da ocorrência, para ela aparecer mesmo com o painel estreito
const lead = (t) => { t = t.trimStart(); return t.length > 16 ? "…" + t.slice(-16) : t; };

function toggleProjectSearch(open = psearch.hidden) {
  psearch.hidden = !open;
  $("#tree").hidden = open;
  $("#outline").hidden = open;
  $("#btn-project-search").classList.toggle("on", open);
  if (open) {
    const sel = cm.getSelection();
    if (sel && !sel.includes("\n") && sel.length < 80) psInput.value = sel;
    if (filesPane.style.display === "none") $("#toggle-files").click();
    if (matchMedia("(max-width: 820px)").matches) filesPane.classList.add("mobile-show");
    psInput.focus();
    psInput.select();
    if (psInput.value) runProjectSearch();
  }
}

async function runProjectSearch() {
  const token = ++psToken;
  const q = psInput.value;
  const out = $("#ps-results");
  if (!q) { out.innerHTML = ""; $("#ps-summary").textContent = ""; return; }
  await saveAll();  // busca no que está na tela, mesmo o que ainda não foi salvo
  const qs = new URLSearchParams({ q, case: +psOpts.case, word: +psOpts.word, regex: +psOpts.regex });
  let r;
  try { r = await api(`${P}/search?${qs}`); } catch (e) {
    if (token === psToken) { out.innerHTML = ""; $("#ps-summary").textContent = e.message; }
    return;
  }
  if (token !== psToken) return;
  const byFile = new Map();
  r.results.forEach((m) => { if (!byFile.has(m.path)) byFile.set(m.path, []); byFile.get(m.path).push(m); });
  $("#ps-summary").textContent = r.results.length
    ? `${fmtNum(r.results.length)}${r.truncated ? "+" : ""} em ${byFile.size} ${byFile.size === 1 ? "arquivo" : "arquivos"}`
    : "Nada encontrado";
  out.innerHTML = [...byFile].map(([path, ms]) => `<div class="ps-file">
      <div class="ps-fname" title="${esc(path)}">${icon("file")}<span>${esc(path)}</span><b>${ms.length}</b></div>
      ${ms.map((m) => `<div class="ps-hit" data-path="${esc(path)}" data-line="${m.line}" data-col="${m.col}" data-len="${m.len}">
        <span class="ln">${m.line}</span><span class="tx">${esc(lead(m.text.slice(0, m.offset)))}<mark>${esc(m.text.slice(m.offset, m.offset + m.len))}</mark>${esc(m.text.slice(m.offset + m.len))}</span></div>`).join("")}
    </div>`).join("");
}

let psTimer;
psInput.addEventListener("input", () => { clearTimeout(psTimer); psTimer = setTimeout(runProjectSearch, 250); });
psInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { clearTimeout(psTimer); runProjectSearch(); }
  if (e.key === "Escape") toggleProjectSearch(false);
});
document.querySelectorAll("#psearch [data-opt]").forEach((b) => {
  b.onclick = () => {
    psOpts[b.dataset.opt] = !psOpts[b.dataset.opt];
    b.classList.toggle("on", psOpts[b.dataset.opt]);
    b.setAttribute("aria-pressed", psOpts[b.dataset.opt]);
    runProjectSearch();
  };
});
$("#ps-results").addEventListener("click", async (e) => {
  const hit = e.target.closest(".ps-hit");
  if (!hit) return;
  $("#ps-results .ps-hit.active")?.classList.remove("active");
  hit.classList.add("active");
  filesPane.classList.remove("mobile-show");
  await goTo(hit.dataset.path, +hit.dataset.line);
  if (state.current !== hit.dataset.path) return;
  const l = +hit.dataset.line - 1, c = +hit.dataset.col;
  cm.setSelection({ line: l, ch: c + +hit.dataset.len }, { line: l, ch: c });
});
// substituir em todos os arquivos (nos arquivos que aparecem nos resultados)
$("#ps-toggle-replace").onclick = () => {
  const open = $("#ps-replace").hidden;
  $("#ps-replace").hidden = !open;
  $("#ps-toggle-replace").classList.toggle("on", open);
  $("#ps-toggle-replace").setAttribute("aria-pressed", open);
  if (open) $("#ps-repl").focus();
};
$("#ps-repl").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("#ps-replace-all").click();
  if (e.key === "Escape") toggleProjectSearch(false);
});
$("#ps-replace-all").onclick = async () => {
  const q = psInput.value;
  const hits = [...document.querySelectorAll("#ps-results .ps-hit")];
  if (!q || !hits.length) return toast("Busque primeiro o que você quer substituir");
  const paths = [...new Set(hits.map((h) => h.dataset.path))];
  const repl = $("#ps-repl").value;
  const ok = await modal({
    title: "Substituir em todos os arquivos",
    body: `<p>Trocar <b>${plural(hits.length, "ocorrência")}</b> de <code>${esc(q)}</code> por <code>${esc(repl) || "(nada)"}</code> em ${plural(paths.length, "arquivo")}?</p>
      <p class="muted small">O projeto é guardado no Histórico antes, então dá para desfazer.</p>`,
    ok: "Substituir tudo",
  });
  if (!ok) return;
  await saveAll();
  try {
    const r = await api(`${P}/replace`, { json: { q, replacement: repl, ...psOpts, paths } });
    const files = Object.keys(r.changed);
    const total = files.reduce((n, p) => n + r.changed[p], 0);
    // recarrega os arquivos abertos que mudaram (já estavam salvos, então nada se perde)
    for (const p of files) {
      if (!state.docs[p]) continue;
      const disk = await api(`${P}/file?path=${encodeURIComponent(p)}`);
      loadDiskVersion(p, disk.content, disk.mtime);
    }
    toast(`${plural(total, "substituição", "substituições")} em ${plural(files.length, "arquivo")}. Dá para desfazer pelo Histórico.`, 5000);
    runProjectSearch();
    if (state.settings.autoCompile) scheduleAutoCompile();
  } catch (e) { toast(e.message); }
};

$("#btn-project-search").onclick = () => toggleProjectSearch();
$("#ps-close").onclick = () => toggleProjectSearch(false);
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "f") {
    e.preventDefault();
    toggleProjectSearch(true);
  }
});

// ------------------------------------------------------------ contagem de palavras
$("#btn-words").onclick = async () => {
  await saveAll();
  const p = panel({ title: "Contagem de palavras", body: '<p class="muted">Contando…</p>', cls: "words" });
  let r;
  try { r = await api(`${P}/wordcount`); } catch (e) { p.el.innerHTML = `<p>${esc(e.message)}</p>`; return; }
  const row = (label, n, hint = "") => `<tr><td>${label}${hint ? `<small>${hint}</small>` : ""}</td><td>${fmtNum(n)}</td></tr>`;
  p.el.innerHTML = `
    <div class="wc-total"><b>${fmtNum(r.words)}</b><span>palavras no documento</span></div>
    <table class="wc-table">
      ${row("Texto", r.text)}
      ${row("Títulos", r.headers, "capítulos, seções…")}
      ${row("Legendas", r.captions, "figuras e tabelas")}
      ${row("Fórmulas no texto", r.inlineMath, "não entram na contagem")}
      ${row("Fórmulas em destaque", r.displayMath, "não entram na contagem")}
    </table>
    ${r.files.length > 1 ? `<details class="wc-files"><summary>Por arquivo (${r.files.length})</summary><table class="wc-table">
      ${r.files.map((f) => row(esc(f.path), f.text + f.headers + f.captions)).join("")}</table></details>` : ""}
    <p class="wc-pdf" id="wc-pdf"></p>
    <p class="muted small">Conta a partir de <b>${esc(state.settings.main)}</b> e dos arquivos que ele inclui, sem comandos, comentários, referências e bibliografia.</p>`;
  const n = await pdfWordCount().catch(() => null);
  const el = p.el.querySelector("#wc-pdf");
  if (el && n !== null) el.innerHTML = `No PDF compilado: <b>${fmtNum(n)}</b> palavras <small>(inclui sumário, cabeçalhos, números de página e referências)</small>`;
};

// ------------------------------------------------------------ histórico de versões
const STATUS = { modified: "alterado", added: "criado depois", removed: "apagado depois", same: "igual" };

function fmtWhen(t) {
  const d = new Date(t * 1000), now = new Date();
  const time = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return `Hoje, ${time}`;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `Ontem, ${time}`;
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" }) + `, ${time}`;
}

async function afterRestore(paths) {
  // descarta as cópias abertas dos arquivos restaurados e recarrega
  paths.forEach((p) => delete state.docs[p]);
  await loadFiles();
  const cur = state.current;
  if (!state.files.some((f) => f.path === cur)) state.current = null;
  if (paths.includes(cur) || !state.current) { state.current = null; await openFile(state.files.some((f) => f.path === cur) ? cur : state.settings.main); }
  loadMeta();
  compile({ auto: true });
}

$("#btn-history").onclick = async () => {
  await saveAll();
  const p = panel({
    title: "Histórico de versões",
    cls: "history",
    body: `<div class="hist">
      <div class="hist-list"><button class="btn primary small" id="hist-save">${icon("save")}Salvar versão agora</button><div id="hist-items"><p class="muted">Carregando…</p></div></div>
      <div class="hist-files" id="hist-files"><p class="muted">Escolha uma versão.</p></div>
      <div class="hist-diff" id="hist-diff"></div>
    </div>`,
  });
  const root = p.el;
  let versions = [], sel = null, selFile = null;

  async function loadVersions() {
    versions = await api(`${P}/history`);
    const items = root.querySelector("#hist-items");
    if (!versions.length) {
      items.innerHTML = '<p class="muted small">Ainda não há versões. O TexDesk guarda uma automaticamente quando você volta a editar depois de 10 minutos, e antes de apagar ou mover arquivos.</p>';
      return;
    }
    items.innerHTML = versions.map((v) => `<button class="hist-item ${v.id === sel ? "on" : ""}" data-id="${v.id}">
      <span class="when">${fmtWhen(v.time)}</span>
      <span class="what">${v.label ? `<b>${esc(v.label)}</b>` : "Automática"} · ${v === versions[versions.length - 1] ? plural(v.files, "arquivo") : plural(v.changed, "arquivo alterado", "arquivos alterados")}</span></button>`).join("");
  }

  async function showVersion(id) {
    sel = id;
    selFile = null;
    root.querySelectorAll(".hist-item").forEach((b) => b.classList.toggle("on", b.dataset.id === id));
    const files = await api(`${P}/history/${id}`);
    const changed = files.filter((f) => f.status !== "same");
    const same = files.filter((f) => f.status === "same");
    const li = (f) => `<button class="hist-file st-${f.status}" data-path="${esc(f.path)}" title="${esc(f.path)}"><span>${esc(f.path)}</span><small>${STATUS[f.status]}</small></button>`;
    root.querySelector("#hist-files").innerHTML = `
      <button class="btn small" id="hist-restore-all" ${changed.length ? "" : "disabled"}>${icon("history")}Restaurar o projeto inteiro</button>
      <h4>Diferente de agora (${changed.length})</h4>${changed.map(li).join("") || '<p class="muted small">Nenhum: esta versão é igual ao projeto atual.</p>'}
      ${same.length ? `<details><summary>Iguais (${same.length})</summary>${same.map(li).join("")}</details>` : ""}`;
    root.querySelector("#hist-diff").innerHTML = changed.length ? '<p class="muted">Escolha um arquivo para ver o que mudou.</p>' : "";
    if (changed.length) showFile(changed[0].path);
  }

  async function showFile(path) {
    selFile = path;
    root.querySelectorAll(".hist-file").forEach((b) => b.classList.toggle("on", b.dataset.path === path));
    const r = await api(`${P}/history/${sel}/diff?path=${encodeURIComponent(path)}`);
    const st = root.querySelector(`.hist-file[data-path="${CSS.escape(path)}"]`)?.className.match(/st-(\w+)/)?.[1];
    const lines = r.diff.map((l) => {
      const hunk = l.match(/^@@ -\d+(?:,\d+)? \+(\d+)/);
      if (hunk) return `<div class="dl hunk">Linha ${Math.max(1, +hunk[1])}</div>`;
      const c = l[0] === "+" ? "add" : l[0] === "-" ? "del" : "";
      return `<div class="dl ${c}">${esc(l) || " "}</div>`;
    }).join("");
    root.querySelector("#hist-diff").innerHTML = `
      <div class="hist-diff-head"><span title="${esc(path)}">${esc(path)}</span>
        <button class="btn small" id="hist-restore-file">${st === "added" ? "Apagar (não existia)" : "Restaurar este arquivo"}</button></div>
      <div class="legend"><span class="del">− como estava na versão</span><span class="add">+ como está agora</span></div>
      <div class="diff">${lines || '<p class="muted">Sem diferenças.</p>'}</div>`;
  }

  async function restore(path) {
    const v = versions.find((x) => x.id === sel);
    const what = path ? `<b>${esc(path)}</b>` : "<b>todos os arquivos de texto</b> do projeto";
    const ok = await modal({
      title: "Restaurar versão",
      body: `<p>Voltar ${what} para a versão de ${esc(fmtWhen(v.time))}?</p><p class="muted small">O estado atual é guardado antes, como uma versão nova, então dá para desfazer.</p>`,
      ok: "Restaurar",
    });
    if (!ok) return;
    try {
      const r = await api(`${P}/history/${sel}/restore`, { json: { path } });
      toast(path ? `${path} restaurado` : `${r.restored.length} arquivo(s) restaurado(s)`);
      await afterRestore(r.restored);
      await loadVersions();
      await showVersion(sel);
    } catch (e) { toast(e.message); }
  }

  root.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.closest(".hist-item")) return showVersion(t.closest(".hist-item").dataset.id);
    if (t.closest(".hist-file")) return showFile(t.closest(".hist-file").dataset.path);
    if (t.closest("#hist-restore-file")) return restore(selFile);
    if (t.closest("#hist-restore-all")) return restore(null);
    if (t.closest("#hist-save")) {
      const r = await modal({ title: "Salvar versão", fields: [{ name: "label", label: "Nome da versão", value: "" }], ok: "Salvar" });
      if (!r || !r.label.trim()) return;
      try {
        await api(`${P}/history`, { json: { label: r.label } });
        await loadVersions();
        toast("Versão salva");
      } catch (err) { toast(err.message); }
    }
  });
  try { await loadVersions(); } catch (e) { root.querySelector("#hist-items").innerHTML = `<p>${esc(e.message)}</p>`; }
};

// ------------------------------------------------------------ corretor ortográfico
// Dicionários Hunspell do LibreOffice, no servidor (funciona sem internet). Só o texto é verificado: comandos,
// matemática, comentários, rótulos, citações e caminhos de arquivo ficam de fora.
const SPELL_LANGS = [
  { value: "", label: "Desligado" },
  { value: "pt_BR", label: "Português (Brasil)" },
  { value: "pt_PT", label: "Português (Portugal)" },
  { value: "en_US", label: "Inglês (EUA)" },
  { value: "en_GB", label: "Inglês (Reino Unido)" },
  { value: "es_ES", label: "Espanhol" },
  { value: "fr_FR", label: "Francês" },
  { value: "it_IT", label: "Italiano" },
  { value: "de_DE", label: "Alemão" },
];
const spell = { lang: "", known: new Map(), dict: new Set(), ignored: new Set(), timer: 0, token: 0 };
// argumentos que não são texto do documento
const SPELL_SKIP = /\\(?:begin|end)\{[^}]*\}(?:\[[^\]]*\]|\{[^}]*\})*|\\(?:includegraphics|input|include|subfile|label|ref|eqref|pageref|autoref|[cC]ref|nameref|cite\w*|parencite|textcite|autocite|url|href|bibliography\w*|addbibresource|usepackage|RequirePackage|documentclass|newcommand|renewcommand|providecommand|newenvironment|setlength|hypersetup|graphicspath|usetikzlibrary|usetheme|usecolortheme|definecolor|color|textcolor|lstinputlisting|inputminted|bibliographystyle)\*?(?:\[[^\]]*\])*\{[^}]*\}|\\[a-zA-Z@]+\*?\[[^\]]*\]|\b\w+\s*=|\S+@\S+|\b(?:https?|ftp):\/\/\S+|\bwww\.\S+/g;
const SPELL_WORD = /\p{L}+(?:['’-]\p{L}+)*/gu;

// idioma do documento pelo babel/polyglossia (o último idioma do babel é o principal)
const BABEL_LANGS = [
  [/^(brazil|brazilian|portuges|portuguese)$/, "pt_BR"], [/^(portugal)$/, "pt_PT"],
  [/^(english|american|USenglish)$/, "en_US"], [/^(british|UKenglish)$/, "en_GB"],
  [/^spanish$/, "es_ES"], [/^(french|francais)$/, "fr_FR"], [/^italian$/, "it_IT"], [/^n?german$/, "de_DE"],
];
function detectLang(text) {
  let names = [];
  const cls = text.match(/^[^%\n]*\\documentclass\[([^\]]*)\]/m);  // ex.: \documentclass[brazil]{abntex2}
  if (cls) names = cls[1].split(",").map((x) => x.trim());
  const babel = text.match(/^[^%\n]*\\usepackage\[([^\]]*)\]\{babel\}/m);
  if (babel) names = babel[1].split(",").map((x) => x.trim().replace(/^main=/, ""));
  const poly = text.match(/^[^%\n]*\\setdefaultlanguage(?:\[([^\]]*)\])?\{(\w+)\}/m) || text.match(/^[^%\n]*\\setmainlanguage(?:\[([^\]]*)\])?\{(\w+)\}/m);
  if (poly) names = [poly[2] === "portuguese" && /variant=portuguese/.test(poly[1] || "") ? "portugal" : poly[2]];
  for (const n of names.reverse()) {
    const hit = BABEL_LANGS.find(([rx]) => rx.test(n));
    if (hit) return hit[1];
  }
  // sem idioma declarado (ex.: a classe carrega o babel por dentro): estima pelo texto
  const count = (rx) => (text.match(rx) || []).length;
  const pt = count(/\b(que|não|uma|para|com|são|dos|das)\b|ção\b|ções\b/gi);
  const en = count(/\b(the|and|which|with|this|that|are|from)\b/gi);
  if (pt >= 10 && pt > en * 2) return "pt_BR";
  if (en >= 10 && en > pt * 2) return "en_US";
  return "";
}

function spellLang() {
  const v = store.get(`spell:${PROJECT}`, null);
  if (v !== null) return SPELL_LANGS.some((l) => l.value === v) ? v : "";  // escolhido nas configurações
  const main = state.docs[state.settings.main];
  return main ? detectLang(main.doc.getValue()) : "";
}

// palavras do trecho visível que precisam ser verificadas: [{line, ch, word}]
function spellCandidates(from, to) {
  // no documento principal, o preâmbulo (antes de \begin{document}) não é texto
  let body = 0;
  for (let l = 0; l < Math.min(cm.lineCount(), 400); l++) {
    if (/^[^%]*\\begin\{document\}/.test(cm.getLine(l))) { body = l + 1; break; }
  }
  const out = [];
  for (let l = Math.max(from, body); l < to; l++) {
    const text = cm.getLine(l);
    if (!text || /^\s*%/.test(text)) continue;
    // fica de fora: o que o realce marca como comando/matemática/comentário e os argumentos de SPELL_SKIP
    const skip = cm.getLineTokens(l, true).filter((t) => t.type).map((t) => [t.start, t.end]);
    for (const m of text.matchAll(SPELL_SKIP)) skip.push([m.index, m.index + m[0].length]);
    for (const m of text.matchAll(SPELL_WORD)) {
      const w = m[0], a = m.index, b = a + w.length;
      if (w.length < 3 || w === w.toUpperCase() || /\p{Lu}/u.test(w.slice(1))) continue;  // siglas, CamelCase
      if (text[a - 1] === "\\" || skip.some(([x, y]) => a < y && b > x)) continue;
      out.push({ line: l, ch: a, word: w });
    }
  }
  return out;
}

const isSpellMark = (m) => m.className === "cm-spell";

async function runSpellcheck() {
  const token = ++spell.token;
  const doc = cm.getDoc();
  if (!spell.lang || !/\.(tex|ltx)$/i.test(state.current || "")) {
    doc.getAllMarks().filter(isSpellMark).forEach((m) => m.clear());
    return;
  }
  const vp = cm.getViewport();
  const from = Math.max(0, vp.from - 20), to = Math.min(cm.lineCount(), vp.to + 20);
  const cands = spellCandidates(from, to);
  const key = (w) => `${spell.lang}:${w.toLowerCase()}`;
  const ask = [...new Set(cands.map((c) => c.word).filter((w) => !spell.known.has(key(w))))];
  if (ask.length) {
    let r;
    try { r = await api("/api/spell", { json: { lang: spell.lang, words: ask } }); } catch (e) {
      if (!spell.warned) { spell.warned = true; toast("Corretor ortográfico: " + e.message, 6000); }
      return;
    }
    const bad = new Set(r.unknown.map((w) => w.toLowerCase()));
    ask.forEach((w) => spell.known.set(key(w), !bad.has(w.toLowerCase())));
  }
  if (token !== spell.token || doc !== cm.getDoc()) return;
  cm.operation(() => {
    doc.findMarks({ line: from, ch: 0 }, { line: to, ch: 0 }).filter(isSpellMark).forEach((m) => m.clear());
    for (const c of cands) {
      const lw = c.word.toLowerCase();
      if (spell.known.get(key(c.word)) || spell.dict.has(lw) || spell.ignored.has(lw)) continue;
      doc.markText({ line: c.line, ch: c.ch }, { line: c.line, ch: c.ch + c.word.length }, { className: "cm-spell" });
    }
  });
}

function scheduleSpellcheck(ms = 500) {
  clearTimeout(spell.timer);
  spell.timer = setTimeout(runSpellcheck, ms);
}
cm.on("change", (c, ch) => {
  // a linha editada perde os sublinhados até a próxima verificação (sem piscar na palavra digitada)
  c.findMarks({ line: ch.from.line, ch: 0 }, { line: ch.from.line + ch.text.length, ch: 0 }).filter(isSpellMark).forEach((m) => m.clear());
  if (spell.lang) scheduleSpellcheck();
});
cm.on("viewportChange", () => { if (spell.lang) scheduleSpellcheck(250); });
cm.on("swapDoc", () => { spell.lang = spellLang(); scheduleSpellcheck(50); });

function applySpellcheck() {
  spell.lang = spellLang();
  scheduleSpellcheck(0);
}
applySpellcheck();

// Dicionário pessoal: fica no servidor (vale em qualquer navegador e não some ao limpar os
// dados do navegador). Até a versão 0.2 ficava no navegador; o que estiver lá é levado junto.
async function loadPersonalDict() {
  try {
    let words = await api("/api/spell/dictionary");
    const local = store.get("spellDict", []);
    if (Array.isArray(local) && local.length) {
      words = await api("/api/spell/dictionary", { json: { add: local } });
      try { localStorage.removeItem("spellDict"); } catch (e) { /* sem storage */ }
    }
    spell.dict = new Set(words.map((w) => w.toLowerCase()));
    if (spell.lang) runSpellcheck();
  } catch (e) { /* sem dicionário pessoal desta vez */ }
}
loadPersonalDict();

async function updatePersonalDict(change) {
  const words = await api("/api/spell/dictionary", { json: change });
  spell.dict = new Set(words.map((w) => w.toLowerCase()));
  return words;
}

// lista das palavras adicionadas, com opção de remover
async function openPersonalDict() {
  const p = panel({ title: "Dicionário pessoal", cls: "pdict", body: '<p class="muted">Carregando…</p>' });
  const render = (words) => {
    p.el.innerHTML = words.length
      ? `<p class="muted small">${plural(words.length, "palavra adicionada", "palavras adicionadas")} pelo clique direito no corretor. Valem para todos os projetos e idiomas.</p>
        <input type="text" class="pdict-filter" placeholder="Filtrar" aria-label="Filtrar palavras">
        <div class="pdict-list">${words.map((w) => `<div class="pdict-row" data-word="${esc(w)}"><span>${esc(w)}</span><button class="icon-btn" title="Remover do dicionário">${icon("trash")}</button></div>`).join("")}</div>`
      : '<p class="muted">Nenhuma palavra ainda. Para adicionar, clique com o botão direito numa palavra sublinhada pelo corretor.</p>';
  };
  try { render(await api("/api/spell/dictionary")); } catch (e) { p.el.innerHTML = `<p>${esc(e.message)}</p>`; return; }
  p.el.addEventListener("input", (e) => {
    if (!e.target.matches(".pdict-filter")) return;
    const q = e.target.value.toLowerCase();
    p.el.querySelectorAll(".pdict-row").forEach((r) => { r.hidden = !r.dataset.word.toLowerCase().includes(q); });
  });
  p.el.addEventListener("click", async (e) => {
    const row = e.target.closest("button") && e.target.closest(".pdict-row");
    if (!row) return;
    try {
      const filter = p.el.querySelector(".pdict-filter")?.value || "";
      render(await updatePersonalDict({ remove: [row.dataset.word] }));
      const input = p.el.querySelector(".pdict-filter");
      if (input && filter) { input.value = filter; input.dispatchEvent(new Event("input", { bubbles: true })); }
      runSpellcheck();
    } catch (err) { toast(err.message); }
  });
}

// clique direito numa palavra sublinhada: sugestões, adicionar ao dicionário, ignorar
let spellMenu = null;
const closeSpellMenu = () => { spellMenu?.remove(); spellMenu = null; };
addEventListener("mousedown", (e) => { if (spellMenu && !spellMenu.contains(e.target)) closeSpellMenu(); }, true);
addEventListener("keydown", (e) => { if (e.key === "Escape") closeSpellMenu(); });
cm.getWrapperElement().addEventListener("contextmenu", async (e) => {
  const pos = cm.coordsChar({ left: e.clientX, top: e.clientY }, "window");
  const mark = cm.findMarksAt(pos).find(isSpellMark);
  if (!mark) return;
  e.preventDefault();
  closeSpellMenu();
  const range = mark.find();
  const word = cm.getRange(range.from, range.to);
  const menu = spellMenu = document.createElement("div");
  menu.className = "spell-menu";
  menu.style.left = Math.min(e.clientX, innerWidth - 290) + "px";
  menu.style.top = Math.min(e.clientY, innerHeight - 280) + "px";
  menu.innerHTML = '<div class="muted">Buscando sugestões…</div>';
  document.body.appendChild(menu);
  let sugg = [];
  try { sugg = await api(`/api/spell/suggest?lang=${spell.lang}&word=${encodeURIComponent(word)}`); } catch (err) { /* sem sugestões */ }
  if (spellMenu !== menu) return;
  menu.innerHTML = (sugg.length
    ? sugg.map((s) => `<button data-fix="${esc(s)}"><b>${esc(s)}</b></button>`).join("")
    : '<div class="muted">Nenhuma sugestão</div>')
    + `<hr><button data-act="add">Adicionar "${esc(word)}" ao dicionário</button><button data-act="ignore">Ignorar</button>`;
  menu.onclick = (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    const r = mark.find();
    if (b.dataset.fix && r) cm.replaceRange(b.dataset.fix, r.from, r.to);
    if (b.dataset.act === "add") {
      spell.dict.add(word.toLowerCase());
      updatePersonalDict({ add: [word] }).catch((err) => toast("Não foi possível salvar no dicionário: " + err.message));
    }
    if (b.dataset.act === "ignore") spell.ignored.add(word.toLowerCase());
    closeSpellMenu();
    runSpellcheck();
    cm.focus();
  };
});
