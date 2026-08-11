# Technical portfolio sources

The concise v1 dossier remains reproducible from `technical-portfolio.html`
and `portfolio.css`. The 42-page v2 engineering dossier is built from
`detailed-engineering-portfolio.html` and `detailed-portfolio.css`. SVG
diagrams and curated privacy-reviewed screenshots live under `assets/`.

After the sibling `e2e` repository has run `npm ci`, build the PDF with:

```bash
node scripts/portfolio/build-portfolio.mjs
node scripts/portfolio/build-detailed-portfolio.mjs
```

The builder fails if an A4 page overflows. The output is:

```text
docs/portfolio/output/Bernard-McGeever-Job-Seeker-Copilot-Technical-Portfolio-2026.pdf
docs/portfolio/output/Bernard-McGeever-Job-Seeker-Copilot-Detailed-Engineering-Portfolio-2026.pdf
```

Both builders fail on A4 page overflow. The v2 builder also requires exactly
42 pages and verifies that every referenced image loaded. Validate page count,
links, fonts and metadata with Poppler, then rasterise every page and inspect
the contact sheet before publishing. Source screenshots must remain free of
credentials, cookies and unnecessary personal data.

The detailed edition is supported by:

- `engineering-portfolio-evidence.md`, the internal claim-to-source/history map;
- `engineering-service-catalogue.json`, the complete 31-repository catalogue;
- `detailed-portfolio-change-report.md`, the v1-to-v2 comparison.

See `shareable-asset-manifest.md` for the reviewed application-pack assets,
their provenance and distribution caveats. Fixture-backed videos and example
documents live in the E2E repository and are not presented as live-provider
evidence.
