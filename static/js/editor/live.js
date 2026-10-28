// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Mudanças feitas fora do editor (um agente de IA, outro programa) aparecem sendo digitadas
// no lugar onde aconteceram, em vez de o arquivo ser trocado de uma vez.
//
// Enquanto a animação roda, d.saved já é a versão do disco: nada é salvo pela metade. O usuário
// pode continuar digitando (cada trecho é seguido por marcas no documento); se trocar de
// arquivo, compilar ou sair da página, a animação termina na hora.

const TYPE_MAX_CHARS = 40000;  // acima disso (o arquivo foi reescrito inteiro), aplica de uma vez
const TYPE_FRAME_MS = 16;

// Linhas com a quebra de linha junto: assim um trecho do texto é só a soma das linhas.
const splitLines = (s) => s.match(/[^\n]*\n|[^\n]+$/g) || [];

// Diferença entre duas versões: trechos { from, to } do texto antigo (em caracteres) e o texto
// que entra no lugar, em ordem. Compara por linhas (LCS no meio, sem o começo e o fim iguais) e
// depois corta o que cada trecho tem de igual nas pontas, para só a parte que mudou ser digitada.
function textDiff(a, b) {
  const A = splitLines(a), B = splitLines(b);
  let pre = 0;
  while (pre < A.length && pre < B.length && A[pre] === B[pre]) pre++;
  let suf = 0;
  while (suf < A.length - pre && suf < B.length - pre && A[A.length - 1 - suf] === B[B.length - 1 - suf]) suf++;
  const a1 = A.slice(pre, A.length - suf), b1 = B.slice(pre, B.length - suf);
  const n = a1.length, m = b1.length;
  const pairs = [];  // linhas iguais [i em a1, j em b1], em ordem
  if (n && m && n * m <= 4e6) {
    const w = m + 1, L = new Uint32Array((n + 1) * w);
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        L[i * w + j] = a1[i] === b1[j] ? L[(i + 1) * w + j + 1] + 1 : Math.max(L[(i + 1) * w + j], L[i * w + j + 1]);
      }
    }
    for (let i = 0, j = 0; i < n && j < m;) {
      if (a1[i] === b1[j]) { pairs.push([i, j]); i++; j++; }
      else if (L[(i + 1) * w + j] >= L[i * w + j + 1]) i++;
      else j++;
    }
  }
  pairs.push([n, m]);

  let offset = A.slice(0, pre).join("").length;  // posição, no texto antigo, da linha a1[i]
  const hunks = [];
  let i = 0, j = 0;
  for (const [pi, pj] of pairs) {
    if (pi > i || pj > j) {
      const oldText = a1.slice(i, pi).join(""), newText = b1.slice(j, pj).join("");
      // tira o que é igual no começo e no fim do trecho
      let s = 0;
      while (s < oldText.length && s < newText.length && oldText[s] === newText[s]) s++;
      let e = 0;
      while (e < oldText.length - s && e < newText.length - s && oldText[oldText.length - 1 - e] === newText[newText.length - 1 - e]) e++;
      hunks.push({ from: offset + s, to: offset + oldText.length - e, text: newText.slice(s, newText.length - e) });
      offset += oldText.length;
    }
    if (pi < n) offset += a1[pi].length;
    i = pi + 1;
    j = pj + 1;
  }
  return hunks;
}

// Aplica a diferença de uma vez (de trás para frente, para as posições continuarem valendo).
function applyDiffNow(d, target) {
  const hunks = textDiff(d.doc.getValue(), target);
  const run = () => {
    for (const h of hunks.reverse()) {
      d.doc.replaceRange(h.text, d.doc.posFromIndex(h.from), d.doc.posFromIndex(h.to), "+externo");
    }
  };
  d.applying = true;
  try { d.doc === cm.getDoc() ? cm.operation(run) : run(); } finally { d.applying = false; }
}

// O arquivo mudou no disco e não há alterações pendentes aqui: mostra a mudança sendo digitada.
function typeDiskVersion(path, content, mtime) {
  const d = state.docs[path];
  if (!d) return;
  finishTyping(d);
  clearTimeout(d.timer);
  const hunks = textDiff(d.doc.getValue(), content);
  d.saved = content;
  d.mtime = mtime;
  const chars = hunks.reduce((t, h) => t + h.text.length, 0);
  if (!hunks.length) return renderTabs();
  if (d.doc !== cm.getDoc() || document.hidden || chars > TYPE_MAX_CHARS) {
    applyDiffNow(d, content);
    renderTabs();
    return;
  }
  // Cada trecho ganha uma marca no documento: se o usuário digitar enquanto a animação roda,
  // as marcas acompanham o texto e as mudanças de fora continuam caindo no lugar certo.
  const doc = d.doc;
  for (const h of hunks) {
    h.range = doc.markText(doc.posFromIndex(h.from), doc.posFromIndex(h.to), { clearWhenEmpty: false });
  }
  // cada trecho leva de 0,25 s a 1 s, conforme quantos trechos mudaram
  const frames = Math.max(15, Math.min(60, Math.round(240 / hunks.length)));
  d.typing = { hunks, i: 0, frames, marks: [], caret: null, timer: null };
  setSaveState("Recebendo alterações…");
  typingStep(d);
}

// Apaga o trecho antigo e prepara o ponto onde o texto novo vai sendo digitado.
function startHunk(d, h) {
  const doc = d.doc;
  const r = h.range.find();
  h.range.clear();
  h.del?.clear();
  if (r && (r.from.line !== r.to.line || r.from.ch !== r.to.ch)) doc.replaceRange("", r.from, r.to, "+externo");
  const at = r ? r.from : doc.posFromIndex(0);
  h.start = doc.setBookmark(at);  // fica antes do texto novo
  h.end = doc.setBookmark(at, { insertLeft: true });  // anda junto com o texto digitado
  h.typed = 0;
  h.started = true;
}

function typingStep(d) {
  const t = d.typing;
  if (!t) return;
  const h = t.hunks[t.i];
  if (!h) return endTyping(d);
  const doc = d.doc;
  const later = (ms) => { t.timer = setTimeout(() => typingStep(d), ms); };
  d.applying = true;
  try {
    if (!h.started) {
      const r = h.range.find();
      if (r && !h.del && (r.from.line !== r.to.line || r.from.ch !== r.to.ch)) {
        h.del = doc.markText(r.from, r.to, { className: "cm-ext-del" });  // mostra por um instante o que sai
        showTypingAt(d, r.from);
        return later(220);
      }
      startHunk(d, h);
    }
    if (h.typed < h.text.length) {
      const chunk = h.text.slice(h.typed, h.typed + Math.max(1, Math.ceil(h.text.length / t.frames)));
      doc.replaceRange(chunk, h.end.find(), undefined, "+externo");
      h.typed += chunk.length;
      showTypingAt(d, h.end.find());
    }
    if (h.typed >= h.text.length) {
      closeHunk(d, h);
      t.i++;
      return later(t.i < t.hunks.length ? 120 : 0);
    }
  } finally { d.applying = false; }
  later(TYPE_FRAME_MS);
}

// Trecho terminado: destaca o texto novo e solta os marcadores.
function closeHunk(d, h) {
  const a = h.start.find(), b = h.end.find();
  if (h.text && a && b) d.typing.marks.push(d.doc.markText(a, b, { className: "cm-ext-ins" }));
  h.start.clear();
  h.end.clear();
}

// Cursor de quem está digitando, e a tela acompanha a digitação.
function showTypingAt(d, pos) {
  const t = d.typing;
  t.caret?.clear();
  const el = document.createElement("span");
  el.className = "cm-ext-caret";
  t.caret = d.doc.setBookmark(pos, { widget: el, insertLeft: true });
  if (d.doc === cm.getDoc()) cm.scrollIntoView(pos, 80);
}

function endTyping(d) {
  const t = d.typing;
  if (!t) return;
  clearTimeout(t.timer);
  t.caret?.clear();
  t.hunks.forEach((h) => { h.del?.clear(); h.range?.clear(); });
  setTimeout(() => t.marks.forEach((m) => m.clear()), 2500);  // o destaque some aos poucos (CSS)
  d.typing = null;
  setSaveState("Salvo");
  renderTabs();
  if (d.doc === cm.getDoc()) scheduleOutline();
  if (d.doc.getValue() !== d.saved) d.timer = setTimeout(() => saveDoc(Object.keys(state.docs).find((p) => state.docs[p] === d)), 700);
  if (state.settings.autoCompile) scheduleAutoCompile();
}

// Termina a animação na hora: o que falta de cada trecho entra de uma vez, no lugar marcado
// (junto com o que o usuário tiver digitado enquanto isso).
function finishTyping(d) {
  const t = d && d.typing;
  if (!t) return;
  clearTimeout(t.timer);
  d.applying = true;
  try {
    const run = () => {
      for (const h of t.hunks.slice(t.i)) {
        if (!h.started) startHunk(d, h);
        d.doc.replaceRange(h.text.slice(h.typed), h.end.find(), undefined, "+externo");
        h.typed = h.text.length;
        closeHunk(d, h);
      }
    };
    d.doc === cm.getDoc() ? cm.operation(run) : run();
  } finally { d.applying = false; }
  t.i = t.hunks.length;
  endTyping(d);
}

const finishAllTyping = () => Object.values(state.docs).forEach(finishTyping);

cm.on("swapDoc", finishAllTyping);
document.addEventListener("visibilitychange", () => { if (document.hidden) finishAllTyping(); });
