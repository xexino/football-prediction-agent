// End-to-end smoke test: loads every dashboard page against a running server, fails on console errors
// or missing headings. Usage: node e2e/smoke.cjs [baseUrl] [screenshotDir]
const { chromium } = require("playwright");
const base = process.argv[2] || "http://localhost:8000";
const shots = process.argv[3];
const pages = [["", "My view"], ["overview", "Overview"], ["upcoming", "Upcoming Matches"], ["predictions", "Predictions"], ["slip", "Virtual Bet Slip"],
  ["history", "Results & History"], ["analytics", "Analytics"], ["sources", "Data Sources & Coverage"], ["system", "System Health"],
  ["insights", "AI Match Insights"], ["compare", "Engine A vs Engine B"], ["engine-b", "Engine B — track record"], ["coverage", "Global coverage & live data"]];
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/fonts\.googleapis|fonts\.gstatic/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  let fail = 0;
  for (const [route, heading] of pages) {
    await page.goto(`${base}/#/${route}`, { waitUntil: "networkidle" });
    await page.waitForSelector("h1", { timeout: 15000 });
    const h1 = await page.textContent("h1");
    const loadErr = await page.$$eval(".err-box", (els) => els.some((e) => e.textContent.startsWith("Failed to load")));
    const ok = h1.trim() === heading && !loadErr;
    console.log(`${ok ? "PASS" : "FAIL"}  /#/${route.padEnd(12)} h1="${h1}"`);
    if (!ok) fail++;
    if (shots) await page.screenshot({ path: `${shots}/${route || "overview"}.png`, fullPage: false });
  }
  // interaction: expand the first predicted fixture on the Upcoming page
  await page.goto(`${base}/#/upcoming`, { waitUntil: "networkidle" });
  await page.waitForSelector("tr.fixture-row", { timeout: 15000 }).catch(() => null);
  const row = await page.$("tr.fixture-row:has(.probbar)");
  if (!row) { console.log("FAIL  no predicted fixture row found"); fail++; }
  if (row) { await row.click(); await page.waitForSelector("tr.detail", { timeout: 5000 }); console.log("PASS  upcoming row expands"); if (shots) await page.screenshot({ path: `${shots}/upcoming-detail.png` }); }
  // AI match detail: open the first analysed match card
  await page.goto(`${base}/#/insights`, { waitUntil: "networkidle" });
  await page.waitForSelector("a.ai-card", { timeout: 15000 }).catch(() => null);
  const card = await page.$("a.ai-card:has(.tri)");
  if (!card) { console.log("FAIL  no analysed match card"); fail++; } else {
    await card.click();
    await page.waitForSelector("text=AI Match Analyst", { timeout: 15000 });
    const hasMatrix = await page.$("table.cs-matrix");
    console.log(`${hasMatrix ? "PASS" : "FAIL"}  match detail shows analyst report + score matrix`);
    if (!hasMatrix) fail++;
    if (shots) await page.screenshot({ path: `${shots}/insight-detail.png`, fullPage: true });
  }
  // mobile layout: no horizontal overflow
  await page.setViewportSize({ width: 390, height: 844 });
  for (const r of ["", "insights", "engine-b"]) {
    await page.goto(`${base}/#/${r}`, { waitUntil: "networkidle" });
    const of = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    if (of) { console.log(`FAIL  mobile overflow on /#/${r}`); fail++; }
    if (shots && r === "insights") await page.screenshot({ path: `${shots}/mobile-insights.png` });
  }
  await page.goto(`${base}/#/`, { waitUntil: "networkidle" });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  console.log(`${overflow ? "FAIL" : "PASS"}  mobile width has no horizontal page scroll`);
  if (overflow) fail++;
  if (shots) await page.screenshot({ path: `${shots}/mobile.png` });
  if (errors.length) { console.log("console errors:\n" + errors.join("\n")); fail++; }
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
