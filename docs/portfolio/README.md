# Technical portfolio sources

The concise v1 dossier remains reproducible from `technical-portfolio.html`
and `portfolio.css`. The 45-page v3 product and engineering confidence dossier is built from
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

Both builders fail on A4 page overflow. The v3 builder also requires exactly
45 pages and verifies that every referenced image loaded. Validate page count,
links, fonts and metadata with Poppler, then rasterise every page and inspect
the contact sheet before publishing. Source screenshots must remain free of
credentials, cookies and unnecessary personal data.

The detailed edition is supported by:

- `engineering-portfolio-evidence.md`, the internal claim-to-source/history map;
- `engineering-service-catalogue.json`, the complete 31-repository catalogue;
- `detailed-portfolio-change-report.md`, the edition-to-edition comparison.

See `shareable-asset-manifest.md` for the reviewed application-pack assets,
their provenance and distribution caveats. The current showcase uses a
fictional persona with explicitly enabled live provider/model boundaries; its
example documents live in the E2E repository and are never presented as real
candidate data or production-availability evidence.
