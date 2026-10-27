// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Compilação, painel de logs e marcadores de erro no código.

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
  let slowHint = 0;
  if (state.firstCompile && !state.pdf) {
    $("#pdf-empty").textContent = "Compilando…";
    // só explica a demora se ela acontecer (pacotes LaTeX novos são baixados uma vez)
    slowHint = setTimeout(() => {
      if (state.compiling && !state.pdf) {
        $("#pdf-empty").innerHTML = "Compilando…<br><small>Baixando os pacotes LaTeX que este documento usa. Isso só acontece na primeira vez.</small>";
      }
    }, 8000);
  }
  try {
    await saveAll();
    // o servidor decide o documento: o aberto, se for completo, ou o que inclui o capítulo aberto
    const r = await api(`${P}/compile`, { json: { open: state.current } });
    state.firstCompile = false;
    if (r.status === "busy") return;
    if (r.main && r.main !== state.settings.main) {
      state.settings.main = r.main;
      renderTree();
      toast(`Documento compilado: ${r.main}`);
    }
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
    clearTimeout(slowHint);
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
    <label title="Com mais de um documento no projeto, compila o que está aberto no editor"><input type="checkbox" data-k="followOpen" ${state.settings.followOpen ? "checked" : ""}> Compilar o documento aberto</label>
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
  $("#btn-logs").innerHTML = icon("logs") + '<span class="hide-xs">Logs</span>' +
    (c.error ? ` <span class="badge err">${c.error}</span>` : "") +
    (c.warning ? ` <span class="badge warn">${c.warning}</span>` : "");
  const list = state.entries.filter((e) => logFilter === "all" || e.level === logFilter);
  const s = state.lastStatus || {};
  const summary = s.status === "success" ? `Compilado em ${s.time}s` : s.status ? (s.time ? `Compilação com problemas (${s.time}s)` : "Compilação com problemas") : "Ainda não compilado";
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
      ${e.content ? `<pre>${esc(e.content)}</pre>` : ""}${hintHtml(e)}</div>`).join("")}
    <details class="log-raw"><summary>Log bruto (.log)</summary><pre>${esc(state.lastLog || "")}</pre></details>
    <details class="log-raw"><summary>Saída do compilador</summary><pre>${esc(state.lastOut || "")}</pre></details>`;
}

// ------------------------------------------------------------ dicas para os erros mais comuns
// comando -> pacote que o define
const CMD_PKG = {
  includegraphics: "graphicx", graphicspath: "graphicx", rotatebox: "graphicx", scalebox: "graphicx", resizebox: "graphicx",
  url: "url", href: "hyperref", hypersetup: "hyperref", autoref: "hyperref", nameref: "hyperref", phantomsection: "hyperref",
  textcolor: "xcolor", color: "xcolor", colorbox: "xcolor", fcolorbox: "xcolor", definecolor: "xcolor", pagecolor: "xcolor",
  rowcolor: "colortbl", cellcolor: "colortbl",
  toprule: "booktabs", midrule: "booktabs", bottomrule: "booktabs", cmidrule: "booktabs", addlinespace: "booktabs",
  SI: "siunitx", si: "siunitx", qty: "siunitx", unit: "siunitx", num: "siunitx", ang: "siunitx", sisetup: "siunitx",
  mathbb: "amssymb", mathfrak: "amssymb", checkmark: "amssymb", varnothing: "amssymb", leqslant: "amssymb", geqslant: "amssymb",
  therefore: "amssymb", because: "amssymb", nexists: "amssymb", blacksquare: "amssymb", square: "amssymb",
  text: "amsmath", dfrac: "amsmath", tfrac: "amsmath", binom: "amsmath", eqref: "amsmath", operatorname: "amsmath",
  DeclareMathOperator: "amsmath", intertext: "amsmath", numberwithin: "amsmath", boldsymbol: "amsmath", tag: "amsmath",
  iint: "amsmath", iiint: "amsmath", overset: "amsmath", underset: "amsmath", xrightarrow: "amsmath",
  theoremstyle: "amsthm", qedhere: "amsthm", qedsymbol: "amsthm",
  mathscr: "mathrsfs", bm: "bm", cancel: "cancel", cancelto: "cancel",
  cref: "cleveref", Cref: "cleveref", crefname: "cleveref",
  multirow: "multirow", makecell: "makecell", thead: "makecell",
  lipsum: "lipsum", blindtext: "blindtext", Blindtext: "blindtext",
  sout: "ulem", uline: "ulem", uuline: "ulem", hl: "soul", st: "soul", ul: "soul",
  ce: "mhchem", pu: "mhchem",
  tikz: "tikz", usetikzlibrary: "tikz", pgfmathsetmacro: "tikz",
  euro: "eurosym", degree: "gensymb", celsius: "gensymb", micro: "gensymb",
  enquote: "csquotes", textquote: "csquotes",
  printbibliography: "biblatex", addbibresource: "biblatex", autocite: "biblatex", parencite: "biblatex",
  textcite: "biblatex", footcite: "biblatex", fullcite: "biblatex",
  citep: "natbib", citet: "natbib", citealp: "natbib", citeauthor: "natbib", citeyear: "natbib",
  lstinline: "listings", lstset: "listings", lstinputlisting: "listings",
  mintinline: "minted", inputminted: "minted", usemintedstyle: "minted",
  captionof: "caption", captionsetup: "caption",
  setstretch: "setspace", onehalfspacing: "setspace", doublespacing: "setspace", singlespacing: "setspace",
  newgeometry: "geometry", restoregeometry: "geometry",
  fancyhead: "fancyhdr", fancyfoot: "fancyhdr", fancyhf: "fancyhdr", lhead: "fancyhdr", rhead: "fancyhdr", chead: "fancyhdr",
  todo: "todonotes", listoftodos: "todonotes", missingfigure: "todonotes",
  xspace: "xspace", FloatBarrier: "placeins", includepdf: "pdfpages", qrcode: "qrcode",
  ifthenelse: "ifthen", equal: "ifthen", adjustbox: "adjustbox",
  setmainfont: "fontspec", setsansfont: "fontspec", setmonofont: "fontspec", newfontfamily: "fontspec",
  newtcolorbox: "tcolorbox", tcbset: "tcolorbox", tcbox: "tcolorbox",
  State: "algpseudocode", Statex: "algpseudocode", Require: "algpseudocode", Ensure: "algpseudocode",
  subfloat: "subfig", columnbreak: "multicol",
  DeclareSIUnit: "siunitx", ding: "pifont", textdegree: "textcomp", texteuro: "textcomp",
  hhline: "hhline", arraybackslash: "array", newcolumntype: "array",
  tnote: "threeparttable",
};
// ambiente -> pacote
const ENV_PKG = {
  align: "amsmath", "align*": "amsmath", gather: "amsmath", "gather*": "amsmath", multline: "amsmath", "multline*": "amsmath",
  split: "amsmath", cases: "amsmath", pmatrix: "amsmath", bmatrix: "amsmath", vmatrix: "amsmath", Vmatrix: "amsmath",
  Bmatrix: "amsmath", matrix: "amsmath", smallmatrix: "amsmath", aligned: "amsmath", alignat: "amsmath", "alignat*": "amsmath",
  "equation*": "amsmath", subequations: "amsmath", proof: "amsthm",
  subfigure: "subcaption", subtable: "subcaption",
  algorithm: "algorithm", algorithmic: "algpseudocode",
  lstlisting: "listings", minted: "minted",
  tikzpicture: "tikz", axis: "pgfplots", circuitikz: "circuitikz", forest: "forest",
  longtable: "longtable", tabularx: "tabularx", tabulary: "tabulary", threeparttable: "threeparttable",
  multicols: "multicol", "multicols*": "multicol", wrapfigure: "wrapfig", wraptable: "wrapfig",
  landscape: "pdflscape", tcolorbox: "tcolorbox", comment: "comment", adjustbox: "adjustbox",
  spacing: "setspace", singlespace: "setspace", onehalfspace: "setspace", doublespace: "setspace",
  "enumerate*": "enumitem", "itemize*": "enumitem", "description*": "enumitem",
};

function levenshtein(a, b) {
  const row = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const tmp = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = tmp;
    }
  }
  return row[b.length];
}

// o mais parecido com "word" numa lista (ou nada, se nenhum for parecido o bastante)
function closest(word, list) {
  let best = null, bestD = Infinity;
  const w = word.toLowerCase();
  for (const c of list) {
    const d = levenshtein(w, c.toLowerCase());
    if (d < bestD) { best = c; bestD = d; }
  }
  return best && bestD > 0 && bestD <= Math.max(2, Math.floor(w.length / 4)) ? best : null;
}

const code = (s) => `<code>${esc(s)}</code>`;
const pkgFix = (pkg) => `<button class="btn small" data-addpkg="${esc(pkg)}">Adicionar ${esc("\\usepackage{" + pkg + "}")}</button>`;

function hintFor(e) {
  const m = e.message || "";
  let r;
  if (/Undefined control sequence/.test(m)) {
    // o TeX quebra a linha logo depois do comando que não conhece
    const first = (e.content || "").split("\n")[0];
    const cmd = (first.match(/\\([A-Za-z@]+)\*?\s*$/) || [])[1];
    if (!cmd) return { text: "Comando desconhecido. Confira se o nome está escrito certo ou se falta carregar algum pacote no preâmbulo." };
    const pkg = CMD_PKG[cmd];
    if (pkg) return { text: `O comando ${code("\\" + cmd)} vem do pacote ${code(pkg)}, que não foi carregado.`, fix: pkg };
    const known = LATEX_COMMANDS.map((c) => c.match(/^[A-Za-z]+/)?.[0]).filter(Boolean);
    const near = closest(cmd, [...new Set(known.concat(Object.keys(CMD_PKG)))]);
    return { text: `O LaTeX não conhece ${code("\\" + cmd)}.${near ? ` Você quis dizer ${code("\\" + near)}?` : " Confira a grafia ou se falta carregar algum pacote."}` };
  }
  if ((r = m.match(/Environment (\S+) undefined/))) {
    const env = r[1], pkg = ENV_PKG[env];
    if (pkg) return { text: `O ambiente ${code(env)} vem do pacote ${code(pkg)}, que não foi carregado.`, fix: pkg };
    if (env === "frame") return { text: `${code("frame")} só existe em apresentações: use ${code("\\documentclass{beamer}")}.` };
    if (/^(theorem|lemma|definition|corollary|proposition|example|remark|teorema|lema|definicao|definição|corolario|exemplo)$/.test(env)) {
      return { text: `Defina o ambiente no preâmbulo antes de usar, por exemplo ${code(`\\newtheorem{${env}}{Teorema}`)} (com o pacote ${code("amsthm")}).` };
    }
    return { text: `O ambiente ${code(env)} não existe. Confira a grafia ou se falta carregar algum pacote.` };
  }
  if ((r = m.match(/File [`'"]?([^`'"]+?)['"]? not found/) || m.match(/Unable to load picture or PDF file '([^']+)'/))) {
    const file = r[1];
    if (/\.(sty|cls)$/.test(file)) {
      return { text: `O pacote ou a classe ${code(file.replace(/\.\w+$/, ""))} não existe. Confira o nome (o TexDesk baixa sozinho os pacotes que existem).` };
    }
    const stem = (f) => f.split("/").pop().replace(/\.\w+$/, "");
    const base = stem(file);
    const cands = state.files.filter((f) => f.type === "file").map((f) => f.path);
    const similar = closest(base, cands.map(stem));
    const near = cands.find((c) => stem(c).toLowerCase() === base.toLowerCase()) || (similar && cands.find((c) => stem(c) === similar));
    return { text: `O arquivo ${code(file)} não está no projeto.${near ? ` Há um parecido: ${code(near)}. Os nomes diferenciam maiúsculas e minúsculas, e o caminho é relativo à pasta do documento principal.` : " Envie o arquivo ou confira o nome e a pasta."}` };
  }
  if (/Missing \$ inserted/.test(m)) return { text: `Um símbolo de matemática (como ${code("_")}, ${code("^")} ou ${code("\\alpha")}) apareceu fora de uma fórmula. Coloque a fórmula entre ${code("$…$")}, ou escreva ${code("\\_")} para um sublinhado no texto.` };
  if (/Misplaced alignment tab character &/.test(m)) return { text: `${code("&")} só separa colunas de tabelas e alinhamentos. Para escrever o símbolo no texto, use ${code("\\&")}.` };
  if (/Extra alignment tab has been changed/.test(m)) return { text: "Esta linha da tabela tem mais colunas que as definidas no {…} do tabular." };
  if (/There's no line here to end/.test(m)) return { text: `${code("\\\\")} foi usado onde não há linha para terminar (por exemplo, numa linha vazia ou logo depois de um título). Para pular espaço, use ${code("\\vspace{…}")} ou uma linha em branco.` };
  if (/Missing } inserted|Extra }, or forgotten|Too many }'s|Extra \\right|Missing \\right/.test(m)) return { text: "As chaves (ou os \\left/\\right) não estão balanceadas: falta fechar ou sobra um fechamento perto desta linha." };
  if (/Runaway argument|File ended while scanning|Paragraph ended before/.test(m)) return { text: "Um argumento entre chaves não foi fechado: falta um } antes do fim do parágrafo ou do arquivo." };
  if ((r = m.match(/\\begin\{([^}]+)\}(?: on input line (\d+))? ended by \\end\{([^}]+)\}/))) return { text: `O ${code(`\\begin{${r[1]}}`)}${r[2] ? ` da linha ${r[2]}` : ""} foi fechado com ${code(`\\end{${r[3]}}`)}. Confira se algum ambiente ficou sem fechar ou se o nome no \\end está errado.` };
  if (/Misplaced \\noalign/.test(m)) return { text: `${code("\\hline")}, ${code("\\toprule")} e parecidos só podem ficar dentro de uma tabela, no começo de uma linha (logo depois de ${code("\\\\")}).` };
  if (/Lonely \\item/.test(m)) return { text: `${code("\\item")} só pode ser usado dentro de ${code("itemize")}, ${code("enumerate")} ou ${code("description")}.` };
  if (/Missing number, treated as zero|Illegal unit of measure/.test(m)) return { text: `Faltou um número ou uma unidade (como ${code("cm")}, ${code("pt")} ou ${code("\\linewidth")}) num tamanho.` };
  if ((r = m.match(/Option clash for package (\S+)/))) return { text: `O pacote ${code(r[1])} foi carregado duas vezes com opções diferentes. Deixe um só ${code("\\usepackage")} com todas as opções (às vezes a classe já o carrega).` };
  if ((r = m.match(/Command (\\\S+) already defined/))) return { text: `${code(r[1])} já existe. Use ${code("\\renewcommand")} para redefinir, ou escolha outro nome.` };
  if (/Can be used only in preamble/.test(m)) return { text: `Este comando só pode ficar no preâmbulo (antes de ${code("\\begin{document}")}).` };
  if (/Missing \\begin\{document\}/.test(m)) return { text: `Há texto no preâmbulo, antes de ${code("\\begin{document}")}, ou o documento principal não é o arquivo certo (mude em Configurações).` };
  if (/Not in outer par mode/.test(m)) return { text: "Uma figura ou tabela flutuante foi colocada dentro de outra caixa (como outra figura, uma minipage ou uma tabela)." };
  if (/Too many unprocessed floats/.test(m)) return { text: `Há figuras e tabelas demais esperando lugar. Use ${code("\\clearpage")} entre elas ou a opção ${code("[htbp]")}.` };
  if ((r = m.match(/Undefined color [`'"]?([^`'"]+)/))) return { text: `A cor ${code(r[1])} não existe. Defina com ${code(`\\definecolor{${r[1]}}{HTML}{…}`)} ou use uma cor do pacote ${code("xcolor")}.` };
  if ((r = m.match(/Citation [`']([^']+)' (?:on page \d+ )?undefined/))) {
    const keys = (projectMeta && projectMeta.citeKeys) || [];
    if (!keys.length) return { text: `A chave ${code(r[1])} não foi encontrada: o projeto não tem nenhum arquivo .bib com referências. Use o botão Referência para importar pelo DOI.` };
    const near = closest(r[1], keys);
    return { text: `A chave ${code(r[1])} não está em nenhum .bib do projeto.${near ? ` Você quis dizer ${code(near)}?` : ""}` };
  }
  if ((r = m.match(/Reference [`']([^']+)' (?:on page \d+ )?undefined/))) {
    const near = closest(r[1], (projectMeta && projectMeta.labels) || []);
    return { text: `Não há ${code(`\\label{${r[1]}}`)} no projeto.${near ? ` Você quis dizer ${code(near)}?` : ""}` };
  }
  if ((r = m.match(/Label [`']([^']+)' multiply defined/))) return { text: `O rótulo ${code(r[1])} aparece em mais de um ${code("\\label")}. Cada rótulo precisa ser único.` };
  if (/Missing character: There is no/.test(m)) return { text: `A fonte usada não tem este caractere. Troque a fonte (pacote ${code("fontspec")}) ou use o comando LaTeX do símbolo.` };
  return null;
}

function hintHtml(e) {
  if (e.level === "typesetting") return "";
  const h = hintFor(e);
  return h ? `<div class="log-hint">${icon("bulb")}<div><span>${h.text}</span>${h.fix ? pkgFix(h.fix) : ""}</div></div>` : "";
}

// acrescenta \usepackage{pkg} no preâmbulo do documento principal, depois do último \usepackage
async function addPackage(pkg) {
  const main = state.settings.main;
  const line = `\\usepackage{${pkg}}`;
  const open = state.docs[main];
  const disk = open ? null : await api(`${P}/file?path=${encodeURIComponent(main)}`);
  const text = open ? open.doc.getValue() : disk.content;
  const lines = text.split("\n");
  const begin = lines.findIndex((l) => /^\s*\\begin\{document\}/.test(l));
  const pre = begin < 0 ? lines : lines.slice(0, begin);
  if (pre.some((l) => new RegExp(`^[^%]*\\\\usepackage(\\[[^\\]]*\\])?\\{[^}]*\\b${pkg}\\b`).test(l))) {
    return toast(`${pkg} já está no preâmbulo`);
  }
  let at = -1;
  pre.forEach((l, i) => { if (/^[^%]*\\(usepackage|RequirePackage)\b/.test(l)) at = i; });
  // sem nenhum \usepackage: logo depois do \documentclass
  if (at < 0) at = pre.findIndex((l) => /^[^%]*\\documentclass/.test(l));
  // o comando pode ocupar várias linhas (opções entre colchetes): insere depois do fim dele
  while (at >= 0 && at + 1 < pre.length && !/\}/.test(pre[at].replace(/%.*/, ""))) at++;
  if (at < 0) return toast("Não encontrei o preâmbulo do documento principal");
  if (open) {
    open.doc.replaceRange(line + "\n", { line: at + 1, ch: 0 });
    await saveDoc(main);
  } else {
    lines.splice(at + 1, 0, line);
    await api(`${P}/file`, { method: "PUT", json: { path: main, content: lines.join("\n"), mtime: disk.mtime } });
  }
  toast(`${line} adicionado em ${main}`);
  loadMeta();
  compile();
}

$("#logs").onclick = (e) => {
  const add = e.target.closest("[data-addpkg]");
  if (add) { e.stopPropagation(); addPackage(add.dataset.addpkg); return; }
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
