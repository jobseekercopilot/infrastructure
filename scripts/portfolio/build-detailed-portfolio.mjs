import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import fs from 'node:fs/promises';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const infrastructureRoot = path.resolve(scriptDirectory, '../..');
const workspaceRoot = path.dirname(infrastructureRoot);
const require = createRequire(import.meta.url);
const { chromium } = require(path.join(workspaceRoot, 'e2e/node_modules/playwright'));

const source = path.join(infrastructureRoot, 'docs/portfolio/detailed-engineering-portfolio.html');
const outputDirectory = path.join(infrastructureRoot, 'docs/portfolio/output');
const output = path.join(
  outputDirectory,
  'Bernard-McGeever-Job-Seeker-Copilot-Detailed-Engineering-Portfolio-2026.pdf'
);
const expectedPages = 45;
await fs.mkdir(outputDirectory, { recursive: true });

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto(pathToFileURL(source).href, { waitUntil: 'load' });
  await page.evaluate(async () => document.fonts.ready);

  const inspection = await page.evaluate(() => {
    const pages = [...document.querySelectorAll('.page')];
    return {
      count: pages.length,
      overflowingPages: pages
        .map((element, index) => ({
          page: index + 1,
          overflowX: element.scrollWidth - element.clientWidth,
          overflowY: element.scrollHeight - element.clientHeight
        }))
        .filter(({ overflowX, overflowY }) => overflowX > 1 || overflowY > 1),
      missingImages: [...document.images]
        .filter((image) => !image.complete || image.naturalWidth === 0)
        .map((image) => image.getAttribute('src'))
    };
  });

  if (inspection.count !== expectedPages) {
    throw new Error(`Expected ${expectedPages} portfolio pages, found ${inspection.count}`);
  }
  if (inspection.missingImages.length > 0) {
    throw new Error(`Portfolio images missing: ${JSON.stringify(inspection.missingImages)}`);
  }
  if (inspection.overflowingPages.length > 0) {
    throw new Error(`Portfolio page overflow detected: ${JSON.stringify(inspection.overflowingPages)}`);
  }

  await page.pdf({
    path: output,
    format: 'A4',
    printBackground: true,
    preferCSSPageSize: true,
    tagged: true,
    outline: true,
    displayHeaderFooter: false,
    margin: { top: '0', right: '0', bottom: '0', left: '0' }
  });
} finally {
  await browser.close();
}

const stat = await fs.stat(output);
console.log(JSON.stringify({ output, pages: expectedPages, bytes: stat.size }));
