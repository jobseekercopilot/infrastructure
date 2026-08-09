document$.subscribe(() => {
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: document.body.getAttribute("data-md-color-scheme") === "slate" ? "dark" : "default",
  });
  mermaid.run({ querySelector: ".mermaid" });
});

