// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Inserir no documento: imagens coladas (Ctrl+V) ou arrastadas para o editor, e
// referências bibliográficas a partir do DOI.

// ------------------------------------------------------------ imagens
const IMG_FOLDERS = /^(figuras|figures|imagens|images|img|imgs|fig|figs)$/i;
// formatos que o XeTeX aceita no \includegraphics
const IMG_TYPES = { "image/png": "png", "image/jpeg": "jpg", "application/pdf": "pdf" };
const IMG_OK = /\.(png|jpe?g|pdf)$/i;

// pasta do documento principal: \includegraphics usa caminhos relativos a ela
function mainDir() {
  const m = state.settings.main || "";
  return m.includes("/") ? m.slice(0, m.lastIndexOf("/") + 1) : "";
}

// a pasta de imagens que o projeto já usa, ou "figuras"
function imageFolder() {
  const base = mainDir();
  const folder = state.files.find((f) => f.type === "folder" && f.path.startsWith(base)
    && !f.path.slice(base.length).includes("/") && IMG_FOLDERS.test(f.path.slice(base.length)));
  return folder ? folder.path.slice(base.length) : "figuras";
}

function freeName(folder, name) {
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name, ext = dot > 0 ? name.slice(dot) : "";
  let cand = name, n = 2;
  while (state.files.some((f) => f.path === folder + "/" + cand)) cand = `${stem}-${n++}${ext}`;
  return cand;
}

function cleanName(name) {
  return name.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^\w.-]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "").toLowerCase() || "imagem";
}

async function insertImages(files) {
  const images = [...files].filter((f) => IMG_TYPES[f.type] || IMG_OK.test(f.name));
  if (!images.length) {
    toast("O LaTeX só aceita imagens PNG, JPG ou PDF. Converta a imagem para um desses formatos.", 5000);
    return true;
  }
  if (!state.current || !/\.tex$/i.test(state.current)) {
    toast("Abra um arquivo .tex para inserir imagens");
    return true;
  }
  const folder = imageFolder();
  const uploadFolder = mainDir() + folder;
  const now = new Date();
  const two = (n) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}${two(now.getMonth() + 1)}${two(now.getDate())}-${two(now.getHours())}${two(now.getMinutes())}${two(now.getSeconds())}`;
  const fd = new FormData();
  const names = [];
  images.forEach((f, i) => {
    // imagens coladas chegam como "image.png": ganham um nome com data e hora
    const generic = !f.name || /^image\.\w+$/i.test(f.name);
    const ext = IMG_TYPES[f.type] || f.name.split(".").pop().toLowerCase();
    const wanted = generic ? `imagem-${stamp}${images.length > 1 ? "-" + (i + 1) : ""}.${ext}` : cleanName(f.name);
    const name = freeName(uploadFolder, wanted);
    names.push(name);
    fd.append("files", f, name);
  });
  fd.append("folder", uploadFolder);
  try {
    await api(`${P}/upload`, { method: "POST", body: fd });
  } catch (e) { toast("Não foi possível enviar a imagem: " + e.message); return true; }
  await loadFiles();
  const blocks = names.map((name) => {
    const label = "fig:" + name.replace(/\.\w+$/, "");
    return ["\\begin{figure}[htbp]", "  \\centering", `  \\includegraphics[width=0.8\\linewidth]{${folder}/${name}}`,
      "  \\caption{}", `  \\label{${label}}`, "\\end{figure}"].join("\n");
  });
  const cur = cm.getCursor();
  const lineText = cm.getLine(cur.line);
  const before = lineText.slice(0, cur.ch).trim() ? "\n" : "";
  const after = lineText.slice(cur.ch).trim() ? "\n" : "";
  cm.replaceRange(before + blocks.join("\n\n") + after, cur);
  // cursor dentro do \caption{} da primeira figura, para já escrever a legenda
  const start = cur.line + (before ? 1 : 0);
  cm.setCursor({ line: start + 3, ch: "  \\caption{".length });
  cm.focus();
  toast(names.length === 1 ? `Imagem salva em ${folder}/${names[0]}` : `${names.length} imagens salvas em ${folder}/`);
  return true;
}

cm.on("paste", (c, e) => {
  const files = [...(e.clipboardData?.files || [])];
  if (!files.some((f) => /^image\//.test(f.type))) return;
  e.preventDefault();
  insertImages(files);
});
cm.on("drop", (c, e) => {
  const files = [...(e.dataTransfer?.files || [])];
  if (!files.length || !files.some((f) => /^image\//.test(f.type) || IMG_OK.test(f.name))) return;
  e.preventDefault();
  c.setCursor(c.coordsChar({ left: e.clientX, top: e.clientY }, "window"));
  insertImages(files);
});

// ------------------------------------------------------------ referência pelo DOI
async function textOf(path) {
  if (state.docs[path]) return state.docs[path].doc.getValue();
  return (await api(`${P}/file?path=${encodeURIComponent(path)}`)).content;
}

async function appendToFile(path, text) {
  const d = state.docs[path];
  if (d) {  // aberto no editor: acrescenta no documento (dá para desfazer com Ctrl+Z)
    const last = d.doc.lastLine();
    const end = { line: last, ch: d.doc.getLine(last).length };
    const sep = d.doc.getValue().trim() ? (d.doc.getValue().endsWith("\n") ? "\n" : "\n\n") : "";
    d.doc.replaceRange(sep + text, end);
    await saveDoc(path);
    return;
  }
  const exists = state.files.some((f) => f.path === path);
  const cur = exists ? await api(`${P}/file?path=${encodeURIComponent(path)}`) : { content: "", mtime: null };
  const sep = cur.content.trim() ? (cur.content.endsWith("\n") ? "\n" : "\n\n") : "";
  await api(`${P}/file`, { method: "PUT", json: { path, content: cur.content + sep + text, mtime: cur.mtime } });
}

$("#btn-cite").onclick = async () => {
  const bibs = state.files.filter((f) => /\.bib$/i.test(f.path)).map((f) => f.path);
  const NEW = "__novo__";
  const target = bibs.length ? bibs : [{ value: NEW, label: `Criar ${mainDir()}referencias.bib` }];
  const inTex = state.current && /\.tex$/i.test(state.current);
  const r = await modal({
    title: "Adicionar referência pelo DOI",
    fields: [
      { name: "doi", label: "DOI ou link", value: "", placeholder: "10.1038/nature14539 ou https://doi.org/…", hint: "A referência em BibTeX vem do doi.org (precisa de internet)." },
      { name: "bib", label: "Arquivo de referências", type: "select", value: target[0].value ?? target[0], options: target },
      ...(inTex ? [{ name: "cite", label: "Inserir \\cite{…} na posição do cursor", type: "check", value: true }] : []),
    ],
    ok: "Adicionar",
  });
  if (!r || !r.doi.trim()) return;
  const bib = r.bib === NEW ? mainDir() + "referencias.bib" : r.bib;
  const cursor = cm.getCursor();
  const doc = cm.getDoc();
  toast("Buscando a referência…", 2000);
  let ref;
  try { ref = await api(`/api/doi?doi=${encodeURIComponent(r.doi)}`); } catch (e) { return toast(e.message, 5000); }
  try {
    const current = state.files.some((f) => f.path === bib) ? await textOf(bib) : "";
    let key = ref.key, bibtex = ref.bibtex;
    if (current.toLowerCase().includes(ref.doi.toLowerCase())) {
      const m = current.match(new RegExp(`@\\w+\\s*\\{\\s*([^,\\s]+)\\s*,[^@]*${ref.doi.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "i"));
      key = m ? m[1] : key;
      toast(`Essa referência já está em ${bib}${m ? ` (chave ${key})` : ""}`, 5000);
    } else {
      // chave repetida (mesmo autor e ano): LeCun_2015a, LeCun_2015b…
      const keys = new Set([...current.matchAll(/@\w+\s*\{\s*([^,\s]+)\s*,/g)].map((m) => m[1]));
      if (keys.has(key)) {
        let c = 97;
        while (keys.has(key + String.fromCharCode(c))) c++;
        const nk = key + String.fromCharCode(c);
        bibtex = bibtex.replace(`{${key},`, `{${nk},`);
        key = nk;
      }
      await appendToFile(bib, bibtex);
      toast(`Referência ${key} adicionada em ${bib}`, 4000);
    }
    if (r.cite && cm.getDoc() === doc) {
      cm.replaceRange(`\\cite{${key}}`, cursor);
      cm.focus();
    }
    await loadFiles();
    renderTabs();
    loadMeta();
  } catch (e) { toast(e.message, 5000); }
};
