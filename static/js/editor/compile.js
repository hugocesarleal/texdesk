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
