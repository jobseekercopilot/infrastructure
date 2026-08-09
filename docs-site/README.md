# Job Seeker Copilot documentation site

The central platform documentation is built with MkDocs Material. Source is in
`docs-site/docs`; navigation and theme configuration are in
`docs-site/mkdocs.yml`.

## Run locally

From the Infrastructure repository root:

```bash
python3 -m venv .venv-docs
. .venv-docs/bin/activate
python -m pip install -r docs-site/requirements.txt
mkdocs serve -f docs-site/mkdocs.yml
```

Open <http://127.0.0.1:8000/>.

## Build

```bash
mkdocs build --strict -f docs-site/mkdocs.yml
```

The static output is `docs-site/site/` and is ignored by Git.
The source `docs/CNAME` file is copied to the artifact root so GitHub Pages
retains the canonical `docs.jobseekercopilot.com` custom domain.

## Publish

The `Docs Pages` GitHub Actions workflow is manual-only. In GitHub, select
**Actions → Docs Pages → Run workflow**. It builds the selected ref, uploads
the static artifact, and deploys it through GitHub Pages. It consumes Actions
minutes only when deliberately run.

Repository administrators must select **GitHub Actions** as the Pages source
once under **Settings → Pages**.

The public, canonical documentation address is
<https://docs.jobseekercopilot.com/>. The underlying GitHub Pages project URL
is a hosting implementation detail and should not be used in user-facing links.

If the repository instead uses the classic `gh-pages` branch model, no workflow
is required:

```bash
mkdocs gh-deploy --clean -f docs-site/mkdocs.yml
```

That command builds and pushes generated static files to `gh-pages`; do not
commit `docs-site/site/` to `develop`.
