// TexDesk — https://github.com/hugocesarleal/texdesk
// Copyright (c) 2026 Hugo César Leal (https://github.com/hugocesarleal)
// SPDX-License-Identifier: MIT

// Autocompletar de LaTeX: comandos, ambientes, \ref, \cite e pacotes.

const LATEX_COMMANDS = [
  "documentclass{}", "usepackage{}", "usepackage[]{}", "begin{}", "end{}", "section{}", "section*{}",
  "subsection{}", "subsubsection{}", "paragraph{}", "chapter{}", "part{}", "title{}", "author{}", "date{}",
  "maketitle", "tableofcontents", "listoffigures", "listoftables", "label{}", "ref{}", "eqref{}", "pageref{}",
  "cite{}", "citep{}", "citet{}", "footnote{}", "textbf{}", "textit{}", "emph{}", "underline{}", "texttt{}",
  "textsc{}", "textsf{}", "textrm{}", "mathbf{}", "mathrm{}", "mathit{}", "mathcal{}", "mathbb{}", "mathsf{}",
  "frac{}{}", "dfrac{}{}", "sqrt{}", "sqrt[]{}", "sum", "prod", "int", "iint", "oint", "lim", "infty",
  "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta", "vartheta", "iota",
  "kappa", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma", "tau", "upsilon", "phi", "varphi", "chi", "psi",
  "omega", "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Phi", "Psi", "Omega",
  "left(", "right)", "left[", "right]", "left\\{", "right\\}", "cdot", "cdots", "ldots", "vdots", "ddots",
  "times", "div", "pm", "mp", "leq", "geq", "neq", "approx", "equiv", "sim", "propto", "in", "notin",
  "subset", "subseteq", "supset", "cup", "cap", "forall", "exists", "partial", "nabla", "to", "rightarrow",
  "leftarrow", "Rightarrow", "Leftarrow", "Leftrightarrow", "mapsto", "hat{}", "bar{}", "vec{}", "dot{}",
  "tilde{}", "overline{}", "underbrace{}", "overbrace{}", "binom{}{}", "text{}", "operatorname{}",
  "includegraphics{}", "includegraphics[width=\\linewidth]{}", "caption{}", "centering", "item",
  "hline", "cline{}", "multicolumn{}{}{}", "multirow{}{}{}", "newcommand{}{}", "renewcommand{}{}",
  "newenvironment{}{}{}", "input{}", "include{}", "bibliography{}", "bibliographystyle{}", "printbibliography",
  "addbibresource{}", "url{}", "href{}{}", "hspace{}", "vspace{}", "newpage", "clearpage", "noindent",
  "small", "large", "Large", "LARGE", "huge", "Huge", "footnotesize", "scriptsize", "tiny", "normalsize",
  "linewidth", "textwidth", "today", "LaTeX", "TeX", "quad", "qquad", "displaystyle", "limits",
  "setlength{}{}", "geometry{}", "hypersetup{}", "frametitle{}", "pause", "usetheme{}", "titlepage",
  "appendix", "verb||", "color{}", "textcolor{}{}", "definecolor{}{}{}", "label{fig:}", "label{eq:}",
  "label{sec:}", "label{tab:}", "autoref{}", "cref{}", "si{}", "SI{}{}", "num{}",
];

const LATEX_ENVS = [
  "document", "figure", "figure*", "table", "table*", "tabular", "tabularx", "equation", "equation*", "align",
  "align*", "gather", "gather*", "multline", "split", "cases", "matrix", "pmatrix", "bmatrix", "vmatrix",
  "itemize", "enumerate", "description", "center", "flushleft", "flushright", "quote", "quotation",
  "verbatim", "abstract", "minipage", "theorem", "lemma", "proof", "definition", "corollary", "frame",
  "block", "columns", "column", "thebibliography", "tikzpicture", "lstlisting", "minted", "array",
  "subfigure", "wrapfigure", "appendices", "titlepage",
];

const LATEX_PACKAGES = [
  "amsmath", "amssymb", "amsthm", "graphicx", "hyperref", "geometry", "babel", "fontspec", "inputenc",
  "fontenc", "xcolor", "tikz", "pgfplots", "booktabs", "tabularx", "multirow", "longtable", "array",
  "float", "caption", "subcaption", "wrapfig", "listings", "minted", "biblatex", "natbib", "cleveref",
  "siunitx", "enumitem", "fancyhdr", "setspace", "titlesec", "tocloft", "xparse", "etoolbox", "lipsum",
  "csquotes", "microtype", "mathtools", "physics", "algorithm2e", "algorithmic", "algpseudocode",
  "abntex2cite", "indentfirst", "lmodern", "url", "parskip", "makeidx", "glossaries", "todonotes",
];

let projectMeta = { labels: [], citeKeys: [], packages: [] };

function latexHint(cm) {
  const cur = cm.getCursor();
  const line = cm.getLine(cur.line).slice(0, cur.ch);

  const arg = line.match(/\\(\w+\*?)(?:\[[^\]]*\])?\{([^{}]*)$/);
  if (arg) {
    const cmd = arg[1];
    const typed = arg[2].split(",").pop().trimStart();
    let list = null;
    if (/^(ref|eqref|pageref|autoref|cref|Cref|nameref|vref)$/.test(cmd)) list = projectMeta.labels;
    else if (/cite/i.test(cmd)) list = projectMeta.citeKeys;
    else if (cmd === "begin" || cmd === "end") list = LATEX_ENVS;
    else if (cmd === "usepackage" || cmd === "RequirePackage") list = LATEX_PACKAGES;
    if (!list) return null;
    const from = CodeMirror.Pos(cur.line, cur.ch - typed.length);
    const items = list.filter((x) => x.toLowerCase().startsWith(typed.toLowerCase()));
    return items.length ? { list: items, from, to: cur } : null;
  }

  const m = line.match(/\\([a-zA-Z]*)$/);
  if (!m) return null;
  const typed = m[1];
  const from = CodeMirror.Pos(cur.line, cur.ch - typed.length);
  const items = [];
  if ("begin".startsWith(typed)) {
    LATEX_ENVS.forEach((env) => {
      if (["document", "itemize", "enumerate", "figure", "table", "equation", "align", "frame", "tabular", "center"].includes(env)) {
        items.push({ text: `begin{${env}}`, displayText: `begin{${env}} … end{${env}}`, env });
      }
    });
  }
  LATEX_COMMANDS.filter((c) => c.startsWith(typed)).forEach((c) => items.push({ text: c, displayText: c }));
  if (!items.length || (items.length === 1 && items[0].text === typed)) return null;
  items.forEach((it) => {
    it.hint = (cm2, data, completion) => {
      const lineStart = cm2.getLine(data.from.line).match(/^\s*/)[0];
      if (completion.env) {
        const body = completion.env === "itemize" || completion.env === "enumerate" ? "\\item " : "";
        const text = `begin{${completion.env}}\n${lineStart}  ${body}\n${lineStart}\\end{${completion.env}}`;
        cm2.replaceRange(text, data.from, data.to);
        cm2.setCursor(CodeMirror.Pos(data.from.line + 1, lineStart.length + 2 + body.length));
        return;
      }
      cm2.replaceRange(completion.text, data.from, data.to);
      // cursor dentro do primeiro {} ou []
      const idx = completion.text.search(/\{\}|\[\]|\|\|/);
      if (idx >= 0) cm2.setCursor(CodeMirror.Pos(data.from.line, data.from.ch + idx + 1));
    };
  });
  return { list: items.slice(0, 60), from, to: cur };
}
