# Technical portfolio source

`technical-portfolio.html` and `portfolio.css` are the reproducible A4 source
for the employer/partner dossier. SVG diagrams and curated privacy-reviewed
screenshots live under `assets/`.

After the sibling `e2e` repository has run `npm ci`, build the PDF with:

```bash
node scripts/portfolio/build-portfolio.mjs
```

The builder fails if an A4 page overflows. The output is:

```text
docs/portfolio/output/Bernard-McGeever-Job-Seeker-Copilot-Technical-Portfolio-2026.pdf
```

Validate page count, links, fonts and metadata with Poppler, then rasterise
every page and inspect the contact sheet before publishing. Source screenshots
must remain free of credentials, cookies and unnecessary personal data.

See `shareable-asset-manifest.md` for the reviewed application-pack assets,
their provenance and distribution caveats. Fixture-backed videos and example
documents live in the E2E repository and are not presented as live-provider
evidence.
