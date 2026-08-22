// Disable Mermaid's DOMContentLoaded auto-run before Material's document hook.
// The Markdown extension emits <pre><code>, while Mermaid 11 expects a plain
// diagram container.
mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });

const renderMermaid = () => {
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: document.body.getAttribute("data-md-color-scheme") === "slate" ? "dark" : "default",
  });

  document.querySelectorAll("pre.mermaid").forEach((source) => {
    const diagram = document.createElement("div");
    diagram.className = "mermaid";
    diagram.textContent = source.textContent;
    source.replaceWith(diagram);
  });

  const diagrams = Array.from(document.querySelectorAll(".mermaid:not([data-processed])"));
  if (diagrams.length > 0) {
    mermaid.run({ nodes: diagrams });
  }
};

renderMermaid();
document$.subscribe(renderMermaid);
