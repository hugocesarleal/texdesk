// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Oferta de importação dos projetos que estão no Drive mas não neste computador.

// ------------------------------------------------------------ importar projetos que já estão no Drive
// Ao conectar (ou abrir o painel já conectado), se o Drive tiver projetos do TexDesk que não
// existem neste computador, pergunta se o usuário quer importá-los. Os importados ficam com a
// sincronização ligada. A resposta é lembrada: os recusados não são oferecidos de novo
// (continuam na aba "Só no Drive" do painel do Google Drive).
let importPromptShown = false;

async function offerDriveImport() {
  if (importPromptShown) return;
  let cands;
  try { cands = await api("/api/drive/import-candidates"); } catch (e) { return; }
  if (!cands.length || importPromptShown) return;
  importPromptShown = true;

  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal wide">
      <h2>Projetos encontrados no seu Google Drive</h2>
      <p class="note" style="font-size:13.5px">Seu Drive tem ${cands.length === 1 ? "1 projeto" : cands.length + " projetos"} do TexDesk que não ${cands.length === 1 ? "está" : "estão"} neste computador. Quer importar? Os projetos importados continuam sincronizados com o Drive: o que você alterar aqui é salvo lá.</p>
      <div class="imp-head"><label class="imp-all"><input type="checkbox" checked> Selecionar todos</label></div>
      <div class="dp-list imp-list">${cands.map((c) => `<label class="dp-row imp-row">
          <input type="checkbox" value="${esc(c.id)}" data-name="${esc(c.name)}" checked>
          <span class="drive-ind drive-ok">${icon("folder")}</span>
          <span class="nm">${esc(c.name)}</span>
          <span class="st drive-off">${c.modified ? "alterado " + timeAgo(Date.parse(c.modified) / 1000) : ""}</span>
        </label>`).join("")}</div>
      <div id="imp-progress" hidden></div>
      <div class="actions"><button class="btn" data-later>Agora não</button>
        <button class="btn primary" data-import>Importar</button></div>
    </div>`;
  document.body.appendChild(bg);
  const boxes = [...bg.querySelectorAll(".imp-list input")];
  const all = bg.querySelector(".imp-all input");
  const btn = bg.querySelector("[data-import]");
  const refreshCount = () => {
    const n = boxes.filter((b) => b.checked).length;
    btn.textContent = n ? `Importar ${n === 1 ? "1 projeto" : n + " projetos"}` : "Importar";
    btn.disabled = !n;
    all.checked = n === boxes.length;
    all.indeterminate = n > 0 && n < boxes.length;
  };
  boxes.forEach((b) => (b.onchange = refreshCount));
  all.onchange = () => { boxes.forEach((b) => (b.checked = all.checked)); refreshCount(); };
  refreshCount();

  const markOffered = () => api("/api/drive/offered", { json: { ids: cands.map((c) => c.id) } }).catch(() => {});
  bg.querySelector("[data-later]").onclick = async () => {
    await markOffered();
    bg.remove();
    toast("Tudo bem. Os projetos continuam no Drive: use Google Drive → Só no Drive para baixar depois.", 6000);
  };

  btn.onclick = async () => {
    const chosen = boxes.filter((b) => b.checked).map((b) => ({ id: b.value, name: b.dataset.name }));
    bg.querySelector(".imp-head").hidden = true;
    bg.querySelector(".imp-list").hidden = true;
    bg.querySelector(".actions").hidden = true;
    const prog = bg.querySelector("#imp-progress");
    prog.hidden = false;
    const done = [], failed = [];
    for (const [i, c] of chosen.entries()) {
      prog.innerHTML = `<div class="dp-progress busy">${icon("cloudUp")}<div class="grow">
          <b>Importando ${i + 1} de ${chosen.length}: ${esc(c.name)}</b>
          <small>Baixando os arquivos do Drive…</small>
          <div class="bar"><span style="width:${Math.round((i / chosen.length) * 100)}%"></span></div></div></div>`;
      try {
        const r = await api("/api/drive/import", { json: c });
        done.push(r);
      } catch (e) { failed.push({ name: c.name, error: e.message }); }
    }
    await markOffered();
    prog.innerHTML = `<div class="dp-progress ${failed.length ? "err" : "ok"}">${icon(failed.length ? "cloudOff" : "cloudCheck")}<div class="grow">
        <b>${done.length} ${done.length === 1 ? "projeto importado" : "projetos importados"}${failed.length ? `, ${failed.length} com erro` : ""}</b>
        <small>${done.length ? "Eles já aparecem na sua lista e continuam sincronizados com o Drive." : ""}</small></div></div>
      ${failed.map((f) => `<div class="err-box" style="margin-top:8px">${esc(f.name)}: ${esc(f.error)}</div>`).join("")}
      ${done.some((d) => !chosen.find((c) => c.name === d.name)) ? `<p class="note" style="margin-top:8px">Alguns nomes foram ajustados porque já existia um projeto com o mesmo nome neste computador.</p>` : ""}
      <div class="actions" style="margin-top:12px"><button class="btn primary" data-close>Fechar</button></div>`;
    prog.querySelector("[data-close]").onclick = () => bg.remove();
    load();
  };
}
