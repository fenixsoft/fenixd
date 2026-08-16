const { chromium } = require('playwright');
const path = require('path');

(async () => {
  // 从项目根（cwd）解析 dist 目录，避免硬编码项目路径
  const extensionPath = path.resolve(process.cwd(), 'dist');
  console.log('Extension path:', extensionPath);

  const userDataDir = '/tmp/fenix-chrome-profile';

  const browserContext = await chromium.launchPersistentContext(userDataDir, {
    headless: false,
    args: [
      `--disable-extensions-except=${extensionPath}`,
      `--load-extension=${extensionPath}`,
    ],
    viewport: { width: 1280, height: 800 },
  });

  // Wait for the extension to load
  await new Promise(r => setTimeout(r, 3000));

  // Open a new tab - this should trigger the newtab override
  const page = await browserContext.newPage();
  await page.waitForTimeout(2000);

  console.log('Page title:', await page.title());
  console.log('Page URL:', page.url());

  // Keep browser open
  console.log('Browser ready. Press Ctrl+C to close.');
  console.log('CDP endpoint: use playwright-cli attach --cdp=chrome to connect');

  // Wait indefinitely
  await new Promise(() => {});
})();
