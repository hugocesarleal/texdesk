// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Diálogo de novo projeto: nome e escolha do modelo.

// ------------------------------------------------------------ novo projeto (nome + escolha do modelo)
const TEMPLATE_ICONS = { blank: "file", "ifmg-slides": "slides", "ifmg-artigo": "fileText", abnt: "book" };

$("#new").onclick = async () => {
  let tpls;
  try { tpls = await api("/api/templates"); } catch (e) { toast(e.message); return; }
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<form class="modal wide" novalidate>
      <h2>Novo projeto</h2>
      <label>Nome do projeto<input type="text" name="name" autocomplete="off" placeholder="Ex.: Trabalho de Redes"></label>
      <div class="field-error" id="np-err" hidden></div>
      <div class="tpl-label">Modelo</div>
      <div class="tpl-grid" role="radiogroup">
        ${tpls.map((t, i) => `<label class="tpl-card">
            <input type="radio" name="template" value="${esc(t.id)}" ${i === 0 ? "checked" : ""}>
            <span class="tpl-ic">${icon(TEMPLATE_ICONS[t.id] || "file")}</span>
            <b>${esc(t.name)}</b><small>${esc(t.description)}</small>
            ${t.source ? `<a class="tpl-src" href="${esc(t.source)}" target="_blank" rel="noopener" title="Repositório original do modelo">${icon("external")}${esc(t.source.replace(/^https?:\/\/(github\.com\/|www\.)?/, "").replace(/\/$/, ""))}</a>` : ""}
          </label>`).join("")}
      </div>
      <div class="actions"><button type="button" class="btn" data-cancel>Cancelar</button>
        <button type="submit" class="btn primary">Criar projeto</button></div>
    </form>`;
  const form = bg.querySelector("form");
  const nameEl = form.elements.name;
  const err = form.querySelector("#np-err");
  const close = () => bg.remove();
  bg.addEventListener("mousedown", (e) => { if (e.target === bg) close(); });
  form.querySelector("[data-cancel]").onclick = close;
  form.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  nameEl.oninput = () => { err.hidden = true; };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const name = nameEl.value.trim();
    if (!name) { err.textContent = "Digite um nome para o projeto."; err.hidden = false; nameEl.focus(); return; }
    const btn = form.querySelector("[type=submit]");
    btn.disabled = true;
    try {
      const p = await api("/api/projects", { json: { name, template: form.elements.template.value } });
      location.href = `/project/${encodeURIComponent(p.name)}`;
    } catch (ex) {
      err.textContent = ex.message; err.hidden = false; btn.disabled = false;
    }
  };
  document.body.appendChild(bg);
  nameEl.focus();
};
