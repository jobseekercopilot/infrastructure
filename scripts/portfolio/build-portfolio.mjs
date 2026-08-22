import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import fs from 'node:fs/promises';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const infrastructureRoot = path.resolve(scriptDirectory, '../..');
const workspaceRoot = path.dirname(infrastructureRoot);
const require = createRequire(import.meta.url);
const { chromium } = require(path.join(workspaceRoot, 'e2e/node_modules/playwright'));

const source = path.join(infrastructureRoot, 'docs/portfolio/technical-portfolio.html');
const outputDirectory = path.join(infrastructureRoot, 'docs/portfolio/output');
const output = path.join(outputDirectory, 'Bernard-McGeever-Job-Seeker-Copilot-Technical-Portfolio-2026.pdf');
await fs.mkdir(outputDirectory, { recursive: true });

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto(pathToFileURL(source).href, { waitUntil: 'load' });
  await page.evaluate(async () => document.fonts.ready);
  const overflowingPages = await page.evaluate(() =>
    [...document.querySelectorAll('.page')]
      .map((element, index) => ({
        page: index + 1,
        overflowX: element.scrollWidth - element.clientWidth,
        overflowY: element.scrollHeight - element.clientHeight
      }))
      .filter(({ overflowX, overflowY }) => overflowX > 1 || overflowY > 1)
  );
  if (overflowingPages.length > 0) {
    throw new Error(`Portfolio page overflow detected: ${JSON.stringify(overflowingPages)}`);
  }
  await page.pdf({
    path: output,
    format: 'A4',
    printBackground: true,
    preferCSSPageSize: true,
    margin: { top: '0', right: '0', bottom: '0', left: '0' }
  });
} finally {
  await browser.close();
}

const stat = await fs.stat(output);
console.log(JSON.stringify({ output, bytes: stat.size }));
