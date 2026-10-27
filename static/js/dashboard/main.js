// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Inicialização do painel (carregado por último).

// volta do login do Google
(function () {
  const q = new URLSearchParams(location.search).get("drive");
  if (!q) return;
  history.replaceState(null, "", "/");
  if (q === "ok") toast("Google Drive conectado!");
  else toast(q, 6000);
  openDrivePanel();
})();
offerDriveImport();

load();
