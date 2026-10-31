// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Busca no código, no mesmo jeito da busca no PDF: mostra as ocorrências enquanto digita,
// ignora maiúsculas e acentos, navega com Enter / Shift+Enter e some ao clicar fora.
// Ctrl+H abre também a linha de substituir.

const codeBar = $("#code-find");
const codeInput = $("#code-find-input");
const replRow = $("#code-find-replace");
const replInput = $("#code-find-repl");
const codeFind = { matches: [], current: -1, marks: [], currentMark: null, text: null, timer: 0 };
const MAX_MARKS = 5000;  // acima disso só conta (marcar tudo deixaria o editor lento)

$("#code-find-prev").innerHTML = icon("chevronUp");
$("#code-find-next").innerHTML = icon("chevron");
$("#code-find-toggle").innerHTML = icon("replace");
$("#code-find-close").innerHTML = icon("close");

// Texto do arquivo sem acentos e em minúsculas, com a posição original de cada caractere
function codeText() {
  const doc = cm.getDoc();
  const gen = doc.changeGeneration();
  if (codeFind.text && codeFind.text.doc === doc && codeFind.text.gen === gen) return codeFind.text;
  const text = doc.getValue();
  let norm = "";
  const map = [];
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    const f = c < "\x80" ? c.toLowerCase() : fold(c);
    norm += f;
    for (let k = 0; k < f.length; k++) map.push(i);
  }
  map.push(text.length);
  codeFind.text = { doc, gen, norm, map };
  return codeFind.text;
}

function clearCodeMarks() {
  cm.operation(() => {
    codeFind.marks.forEach((m) => m.clear());
    if (codeFind.currentMark) codeFind.currentMark.clear();
  });
  codeFind.marks = [];
  codeFind.currentMark = null;
}

// keep: depois de editar o arquivo, refaz a busca sem mexer no cursor nem rolar o editor
function codeSearch(keep = false) {
  clearTimeout(codeFind.timer);
  codeFind.timer = 0;
  const before = codeFind.matches[codeFind.current];
  clearCodeMarks();
  codeFind.matches = [];
  codeFind.current = -1;
  const q = fold(codeInput.value);
  if (!q || codeBar.hidden) return updateCodeCount();
  const { norm, map } = codeText();
  for (let i = norm.indexOf(q); i !== -1; i = norm.indexOf(q, i + q.length)) {
    codeFind.matches.push({ from: map[i], to: map[i + q.length - 1] + 1 });
  }
  if (codeFind.matches.length) {
    // começa no cursor: digitando mais letras, continua na mesma ocorrência
    const from = keep && before ? before.from : cm.indexFromPos(cm.getCursor("from"));
    const i = codeFind.matches.findIndex((m) => m.from >= from);
    codeFind.current = i === -1 ? 0 : i;
    cm.operation(() => {
      for (const m of codeFind.matches.slice(0, MAX_MARKS)) {
        codeFind.marks.push(cm.markText(cm.posFromIndex(m.from), cm.posFromIndex(m.to), { className: "cm-find-hl" }));
      }
    });
  }
  showCodeMatch(!keep);
}

function showCodeMatch(move) {
  if (codeFind.currentMark) codeFind.currentMark.clear();
  codeFind.currentMark = null;
  const m = codeFind.matches[codeFind.current];
  if (m) {
    const from = cm.posFromIndex(m.from);
    const to = cm.posFromIndex(m.to);
    codeFind.currentMark = cm.markText(from, to, { className: "cm-find-current" });
    if (move) {
      cm.setSelection(from, to, { scroll: false });
      cm.scrollIntoView({ from, to }, 80);
    }
  }
  updateCodeCount();
}

function updateCodeCount() {
  const n = codeFind.matches.length;
  const has = !!codeInput.value;
  $("#code-find-count").textContent = !has ? "" : n ? `${codeFind.current + 1} de ${n}` : "Nada encontrado";
  codeBar.classList.toggle("none", has && !n);
}

function stepCode(dir) {
  if (codeBar.hidden) {
    if (!codeInput.value) return openCodeFind();
    codeBar.hidden = false;  // Ctrl+G com a barra fechada: volta a buscar o último texto
    codeSearch(true);
  }
  const n = codeFind.matches.length;
  if (!n) return;
  codeFind.current = (codeFind.current + dir + n) % n;
  showCodeMatch(true);
}

function setReplace(on) {
  replRow.hidden = !on;
  $("#code-find-toggle").classList.toggle("on", on);
  $("#code-find-toggle").setAttribute("aria-pressed", on);
}

function openCodeFind(replace = false) {
  setView("editor");
  codeBar.hidden = false;
  setReplace(replace || !replRow.hidden);
  const sel = cm.getSelection();
  if (sel && sel.length < 200 && !sel.includes("\n")) codeInput.value = sel;
  const field = replace && codeInput.value ? replInput : codeInput;
  field.focus();
  field.select();
  codeSearch();
}

function closeCodeFind(focusEditor = false) {
  if (codeBar.hidden) return;
  codeBar.hidden = true;
  clearTimeout(codeFind.timer);
  codeFind.timer = 0;
  clearCodeMarks();
  codeFind.matches = [];
  if (focusEditor) cm.focus();
}

function replaceCode() {
  const m = codeFind.matches[codeFind.current];
  if (!m) return;
  const from = cm.posFromIndex(m.from);
  cm.replaceRange(replInput.value, from, cm.posFromIndex(m.to), "+substituir");
  cm.setCursor(cm.posFromIndex(m.from + replInput.value.length));
  codeSearch();  // vai para a próxima
}

function replaceAllCode() {
  const all = codeFind.matches;
  if (!all.length) return;
  cm.operation(() => {
    for (const m of [...all].reverse()) {
      cm.replaceRange(replInput.value, cm.posFromIndex(m.from), cm.posFromIndex(m.to), "+substituir");
    }
  });
  toast(all.length === 1 ? "1 substituição" : `${all.length} substituições`);
  codeSearch(true);
}

function barKeys(e) {
  const mod = e.ctrlKey || e.metaKey;
  const k = e.key.toLowerCase();
  if (e.key === "Escape") {
    e.preventDefault();
    closeCodeFind(true);
  } else if (mod && k === "f" && !e.shiftKey) {
    e.preventDefault();
    codeInput.focus();
    codeInput.select();
  } else if (mod && k === "h") {
    e.preventDefault();
    setReplace(replRow.hidden);
    (replRow.hidden ? codeInput : replInput).focus();
  } else if (mod && k === "g") {
    e.preventDefault();
    stepCode(e.shiftKey ? -1 : 1);
  } else return false;
  return true;
}

codeInput.addEventListener("input", () => {
  clearTimeout(codeFind.timer);
  codeFind.timer = setTimeout(codeSearch, 60);
});
codeInput.addEventListener("keydown", (e) => {
  if (barKeys(e)) return;
  if (e.key === "Enter") {
    e.preventDefault();
    // Enter logo depois de digitar: busca o texto novo em vez de pular no resultado antigo
    if (codeFind.timer) codeSearch();
    else stepCode(e.shiftKey ? -1 : 1);
  }
});
replInput.addEventListener("keydown", (e) => {
  if (barKeys(e)) return;
  if (e.key === "Enter") {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) replaceAllCode();
    else replaceCode();
  }
});
$("#code-find-prev").onclick = () => stepCode(-1);
$("#code-find-next").onclick = () => stepCode(1);
$("#code-find-toggle").onclick = () => { setReplace(replRow.hidden); (replRow.hidden ? codeInput : replInput).focus(); };
$("#code-find-close").onclick = () => closeCodeFind(true);
$("#code-find-one").onclick = replaceCode;
$("#code-find-all").onclick = replaceAllCode;

// clicar em qualquer outro lugar (inclusive no próprio código) fecha a busca
document.addEventListener("pointerdown", (e) => {
  if (!codeBar.hidden && !codeBar.contains(e.target) && !e.target.closest("#btn-search, #btn-replace")) closeCodeFind();
}, true);

// o arquivo mudou (substituição, recarregado de fora) ou trocou de aba: refaz a busca
cm.on("changes", () => {
  if (codeBar.hidden) return;
  clearTimeout(codeFind.timer);
  codeFind.timer = setTimeout(() => codeSearch(true), 150);
});
cm.on("swapDoc", () => { if (!codeBar.hidden) codeSearch(); });
