// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Oferta de importação dos projetos que estão no Drive ou no GitHub mas não neste computador.

// ------------------------------------------------------------ importar projetos que já estão lá
// Ao conectar (ou abrir o painel já conectado), se o Drive ou o repositório do GitHub tiver
// projetos do TexDesk que não existem neste computador, pergunta se o usuário quer importá-los.
// Os importados ficam com a sincronização ligada. A resposta é lembrada: os recusados não são
// oferecidos de novo (continuam na aba "Só no Drive"/"Só no GitHub" do painel).
const IMPORT_SOURCES = {
  drive: { api: "/api/drive", label: "Google Drive", short: "Drive", where: "Seu Drive", later: "Google Drive → Só no Drive" },
  github: { api: "/api/github", label: "GitHub", short: "GitHub", where: "Seu repositório no GitHub", later: "GitHub → Só no GitHub" },
};
const importPromptShown = new Set();

const offerDriveImport = () => offerImport("drive");
const offerGithubImport = () => offerImport("github");

async function offerImport(source) {
  const src = IMPORT_SOURCES[source];
  if (importPromptShown.has(source) || document.querySelector(".modal-bg")) return;
  let cands;
  try { cands = await api(`${src.api}/import-candidates`); } catch (e) { return; }
  if (!cands.length || importPromptShown.has(source) || document.querySelector(".modal-bg")) return;
  importPromptShown.add(source);

  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal wide">
      <h2>Projetos encontrados no seu ${src.label}</h2>
      <p class="note" style="font-size:13.5px">${src.where} tem ${cands.length === 1 ? "1 projeto" : cands.length + " projetos"} do TexDesk que não ${cands.length === 1 ? "está" : "estão"} neste computador. Quer importar? Os projetos importados continuam sincronizados com o ${src.short}: o que você alterar aqui é salvo lá.</p>
      <div class="imp-head"><label class="imp-all"><input type="checkbox" checked> Selecionar todos</label></div>
      <div class="dp-list imp-list">${cands.map((c) => `<label class="dp-row imp-row">
          <input type="checkbox" value="${esc(c.id)}" data-name="${esc(c.name)}" checked>
          <span class="drive-ind drive-ok">${icon("folder")}</span>
          <span class="nm">${esc(c.name)}</span>
          <span class="st drive-off">${c.modified ? "alterado " + timeAgo(Date.parse(c.modified) / 1000) : ""}</span>
        </label>`).join("")}</div>
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

  const markOffered = () => api(`${src.api}/offered`, { json: { ids: cands.map((c) => c.id) } }).catch(() => {});
  bg.querySelector("[data-later]").onclick = async () => {
    await markOffered();
    bg.remove();
    toast(`Tudo bem. Os projetos continuam no ${src.short}: use ${src.later} para baixar depois.`, 6000);
  };

  // a importação roda em segundo plano no servidor: a janela fecha na hora e cada projeto
  // aparece na lista como "importando", com o andamento, até chegar inteiro
  btn.onclick = async () => {
    const chosen = boxes.filter((b) => b.checked).map((b) => ({ id: b.value, name: b.dataset.name }));
    btn.disabled = true;
    const queued = [], failed = [];
    for (const c of chosen) {
      try { queued.push(await api(`${src.api}/import`, { json: c })); } catch (e) { failed.push(`${c.name}: ${e.message}`); }
    }
    await markOffered();
    bg.remove();
    if (queued.length) toast(`Importando ${queued.length === 1 ? "1 projeto" : queued.length + " projetos"} do ${src.label} em segundo plano. Você pode continuar usando o TexDesk.`, 5000);
    if (failed.length) toast(`Não foi possível importar: ${failed.join("; ")}`, 8000);
    load();
  };
}
