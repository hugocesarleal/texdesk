// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Compartilhar o projeto pelo GitHub: convidar pessoas (editar ou só ler), mudar a permissão,
// tirar o acesso; para quem recebeu, de quem é o projeto e "Sair do projeto". Um projeto
// compartilhado só para leitura abre sem poder editar.

$("#btn-share").innerHTML = icon("users") + '<span class="hide-sm">Compartilhar</span>';
$("#btn-share").onclick = () => openShare();

// projeto compartilhado com este usuário só para leitura: o editor não deixa mudar nada
async function applyReadOnly() {
  let st;
  try { st = await api(`${P}/share`); } catch (e) { return; }
  state.share = st;
  state.readOnly = !!st.readOnly;
  cm.setOption("readOnly", state.readOnly);
  document.body.classList.toggle("read-only", state.readOnly);
  if (state.readOnly) {
    $("#title").title = `Compartilhado por @${st.shared.owner} só para leitura`;
    toast(`Projeto de @${st.shared.owner}, compartilhado com você só para leitura. Você recebe as atualizações, mas não pode editar (para editar, duplique o projeto no painel).`, 7000);
  }
}

async function openShare() {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal wide share"><h2>Compartilhar ${esc(PROJECT)}</h2><div id="share-body">Carregando…</div>
    <div class="actions"><button class="btn" data-close>Fechar</button></div></div>`;
  const close = () => { bg.remove(); pollGithub(); };
  bg.addEventListener("mousedown", (e) => { if (e.target === bg) close(); });
  bg.querySelector("[data-close]").onclick = close;
  document.body.appendChild(bg);
  const body = bg.querySelector("#share-body");

  const render = (st) => {
    if (!st.connected) {
      body.innerHTML = `<p>Para compartilhar, conecte o GitHub no painel de projetos (botão <b>GitHub</b>). Cada pessoa convidada também precisa de uma conta no GitHub.</p>`;
      return;
    }
    if (st.shared && !st.shared.mine) {
      body.innerHTML = `<p>Projeto de <b>@${esc(st.shared.owner)}</b>, compartilhado com você${st.readOnly ? " <b>só para leitura</b>" : ""}.
          ${st.readOnly ? "Você recebe as atualizações, mas não pode editar." : "O que você edita vai para o projeto de todos."}</p>
        <p><a href="${esc(st.shared.url)}" target="_blank" rel="noopener">${icon("external")} Ver no GitHub</a></p>
        <div class="share-leave"><button class="btn danger small" id="share-leave">Sair do projeto</button>
          <span class="muted small">A cópia neste computador fica, sem sincronizar.</span></div>`;
      body.querySelector("#share-leave").onclick = async () => {
        const ok = await modal({ title: "Sair do projeto?", body: `<p>Você deixa de receber as atualizações de @${esc(st.shared.owner)}. A cópia neste computador continua aqui, como um projeto seu.</p>`, ok: "Sair do projeto", danger: true });
        if (!ok) return;
        try { await api(`${P}/share/leave`, { method: "POST" }); toast("Você saiu do projeto"); close(); location.reload(); } catch (e) { toast(e.message, 6000); }
      };
      return;
    }
    const people = st.people || [];
    body.innerHTML = `
      ${st.shared ? `<p class="muted small">Repositório privado <a href="${esc(st.shared.url)}" target="_blank" rel="noopener">${esc(st.shared.repo)}</a>. Cada edição vai para lá uns 30 segundos depois; quem tem acesso recebe em seguida.</p>`
        : `<p>Convide pessoas pelo usuário do GitHub delas. Na primeira vez, o projeto vai para um repositório privado só dele (<code>texdesk-…</code>) e sai do <code>texdesk-projetos</code>: assim quem você convidar vê só este projeto, não os outros.</p>`}
      <form class="share-invite" id="share-form">
        <input type="text" name="login" placeholder="usuário do GitHub (ex.: maria-silva)" autocomplete="off" spellcheck="false" required>
        <select name="write"><option value="1">Pode editar</option><option value="0">Só pode ler</option></select>
        <button class="btn primary" type="submit">${icon("users")}Convidar</button>
      </form>
      <div class="share-people">${people.length ? people.map((p) => `
        <div class="share-row" data-login="${esc(p.login)}" data-invitation="${p.invitation || ""}">
          <span class="share-avatar">${esc((p.login || "?")[0].toUpperCase())}</span>
          <span class="grow"><b>@${esc(p.login)}</b>${p.pending ? ' <span class="muted small">· convite enviado, ainda não aceito</span>' : ""}</span>
          <select data-perm><option value="1" ${p.write ? "selected" : ""}>Pode editar</option><option value="0" ${p.write ? "" : "selected"}>Só pode ler</option></select>
          <button class="icon-btn" data-remove title="${p.pending ? "Cancelar o convite" : "Tirar o acesso"}">${icon("close")}</button>
        </div>`).join("") : st.shared ? '<p class="muted small">Ninguém mais tem acesso ainda.</p>' : ""}</div>
      ${st.error ? `<div class="err-box">${esc(st.error)}</div>` : ""}
      <p class="muted small">A pessoa recebe o convite por e-mail e no painel do TexDesk dela. Edições no mesmo arquivo são juntadas palavra por palavra; cada commit fica no nome de quem editou.</p>`;
    const form = body.querySelector("#share-form");
    form.onsubmit = async (e) => {
      e.preventDefault();
      const btn = form.querySelector("button");
      btn.disabled = true;
      btn.innerHTML = `${icon("refresh", "spin")}${st.shared ? "Convidando…" : "Criando o repositório…"}`;
      try {
        await saveAll();
        const r = await api(`${P}/share`, { json: { login: form.login.value.trim(), write: form.write.value === "1" } });
        toast(`Convite enviado para @${form.login.value.trim().replace(/^@/, "")}`);
        render(r);
      } catch (err) {
        toast(err.message, 6000);
        btn.disabled = false;
        btn.innerHTML = `${icon("users")}Convidar`;
      }
    };
    body.querySelectorAll(".share-row").forEach((row) => {
      const who = { login: row.dataset.login, invitation: row.dataset.invitation ? +row.dataset.invitation : null };
      row.querySelector("[data-perm]").onchange = async (e) => {
        try { render(await api(`${P}/share/permission`, { json: { ...who, write: e.target.value === "1" } })); } catch (err) { toast(err.message, 6000); }
      };
      row.querySelector("[data-remove]").onclick = async () => {
        const ok = await modal({ title: who.invitation ? "Cancelar o convite?" : `Tirar o acesso de @${who.login}?`, body: who.invitation ? "" : "<p>A pessoa deixa de receber e de enviar alterações. A cópia que ela tem no computador continua com ela.</p>", ok: who.invitation ? "Cancelar convite" : "Tirar o acesso", danger: true });
        if (!ok) return;
        try { render(await api(`${P}/share/remove`, { json: who })); } catch (err) { toast(err.message, 6000); }
      };
    });
  };

  try { render(await api(`${P}/share`)); } catch (e) { body.innerHTML = `<div class="err-box">${esc(e.message)}</div>`; }
}
