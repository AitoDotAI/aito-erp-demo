#!/usr/bin/env node
/* Deep links, cold and by click: a pasted link opens the SAME tenant, view
   and selected row for someone else; clicking writes that state into the
   URL; back/forward restore it; old links without a tenant keep working.

     BASE_URL=http://127.0.0.1:8402 CHROME_PATH=... node scripts/e2e-deeplinks.cjs

   Run by `./do e2e-links` against the BUILT static export served by the
   backend — the production shape. A goto-only test passes even when
   clicking never updates the URL, so the click cases copy the address bar
   and reopen it cold. Each cold case is a NEW browser context, seeded
   with a DIFFERENT stored tenant: the link must win over the recipient's
   own choice. Exit code = number of failed cases. */
const { chromium } = require("playwright-core");

const BASE = (process.env.BASE_URL || "http://127.0.0.1:8402").replace(/\/$/, "");
const TIMEOUT = 45000;

// A supplier only that tenant's universe has (CLAUDE.md, "Per-tenant
// fixture universes"), and the name the switcher shows for it.
const TENANTS = {
  metsa: { name: "Metsä", marker: "Wärtsilä" },
  aurora: { name: "Aurora", marker: "Valio" },
  studio: { name: "Vire", marker: "Adobe" },
};
const OTHER = { metsa: "studio", aurora: "metsa", studio: "aurora" };

let failed = 0;
const check = (ok, label, detail = "") => {
  if (!ok) failed++;
  console.log(`${ok ? "✓" : "✗"} ${label}${detail ? `  (${detail})` : ""}`);
};

const param = (page, key) => new URL(page.url()).searchParams.get(key);
// The prerendered HTML shows the default tenant until the provider has
// read the URL, so the switcher is WAITED on to show the expected name;
// reading it once raced hydration and read "Metsä" on every tenant.
const switcherShows = (page, name) =>
  page.locator(".tenant-name", { hasText: name }).first().waitFor({ timeout: TIMEOUT })
    .then(() => true, () => false);
const showsMarker = (page, t) =>
  page.getByText(TENANTS[t].marker, { exact: false }).first().waitFor({ timeout: TIMEOUT })
    .then(() => true, () => false);

async function cold(browser, url, stored) {
  const ctx = await browser.newContext();
  if (stored) await ctx.addInitScript((s) => { if (!localStorage.getItem("demoTenant")) localStorage.setItem("demoTenant", s); }, stored);
  const page = await ctx.newPage();
  await page.goto(BASE + url, { waitUntil: "domcontentloaded" });
  return { ctx, page };
}

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, headless: true });

  // 1. Cold: every view a tenant shows, opened by a recipient who stored ANOTHER tenant.
  const VIEWS = { metsa: ["/po-queue/", "/supplier/", "/anomalies/"],
                  aurora: ["/po-queue/", "/supplier/", "/inventory/"],
                  studio: ["/po-queue/", "/supplier/", "/projects/"] };
  for (const [t, views] of Object.entries(VIEWS)) {
    for (const v of views) {
      const { ctx, page } = await cold(browser, `${v}?tenant=${t}`, OTHER[t]);
      try {
        const shows = await switcherShows(page, TENANTS[t].name);
        const name = await page.locator(".tenant-name").first().innerText();
        check(shows && param(page, "tenant") === t, `cold ${v}?tenant=${t} with ${OTHER[t]} stored`,
              `switcher "${name}"`);
        if (v !== "/projects/" && v !== "/inventory/" && v !== "/anomalies/") {
          check(await showsMarker(page, t), `  shows ${t}'s data (${TENANTS[t].marker})`);
        }
      } catch (e) { check(false, `cold ${v}?tenant=${t}`, e.message.split("\n")[0]); }
      await ctx.close();
    }
  }

  // 2. By click: select a row, copy the address bar, reopen it cold elsewhere.
  {
    const { ctx, page } = await cold(browser, "/supplier/?tenant=aurora", "metsa");
    try {
      const row = page.locator("table.tbl").nth(1).locator("tbody tr").nth(1);
      const supplier = (await row.locator("td").first().innerText()).trim();
      await row.click();
      await page.waitForURL(/[?&]risk=/, { timeout: TIMEOUT });
      check(param(page, "risk") === supplier, `clicking a risk row writes ?risk=${supplier}`);
      const copied = page.url();
      const reopened = await cold(browser, copied.replace(BASE, ""), "studio");
      const sel = reopened.page.locator("tr.selected").first();
      await sel.waitFor({ timeout: TIMEOUT });
      check((await sel.innerText()).startsWith(supplier) && param(reopened.page, "tenant") === "aurora",
            "  the copied link reopens cold on Aurora with that row selected");
      await reopened.ctx.close();
    } catch (e) { check(false, "click a supplier row", e.message.split("\n")[0]); }

    // 3. The nav keeps the tenant; the old view's selection goes.
    let step = "nav click to PO Queue";
    try {
      await page.locator(".NavBar__menuItem", { hasText: "PO Queue" }).first().click();
      await page.waitForURL(/\/po-queue\//, { timeout: TIMEOUT });
      check(param(page, "tenant") === "aurora" && !param(page, "risk"), "nav click keeps ?tenant=aurora, drops ?risk");
      step = "click a PO row";
      const po = page.locator("table tbody tr", { hasText: /PO-\d+/ }).nth(1);
      const poId = (await po.innerText()).match(/PO-\d+/)[0];
      // The PO-number cell: the row's centre is a "?" that opens the
      // explanation popover instead of selecting the row.
      await po.locator("td").first().click();
      await page.waitForURL(/[?&]po=/, { timeout: TIMEOUT });
      check(param(page, "po") === poId, `clicking a PO writes ?po=${poId}`);

      // 4. A tenant switch is pushed; back/forward restore tenant and row.
      step = "switch to Vire";
      await page.locator(".tenant-trigger").click();
      await page.locator(".tenant-menu-item", { hasText: "Vire" }).click();
      await page.waitForURL(/tenant=studio/, { timeout: TIMEOUT });
      check(await showsMarker(page, "studio"), "switching to Vire writes ?tenant=studio and shows Studio data");
      step = "back";
      await page.goBack();
      await page.waitForURL(/tenant=aurora/, { timeout: TIMEOUT });
      const sel = page.locator("tr.selected").first();
      await sel.waitFor({ timeout: TIMEOUT });
      check((await sel.innerText()).startsWith(poId) && await switcherShows(page, "Aurora"),
            `back restores Aurora with ${poId} selected`);
      step = "forward";
      await page.goForward();
      await page.waitForURL(/tenant=studio/, { timeout: TIMEOUT });
      check(await switcherShows(page, "Vire"), "forward returns to Vire");
    } catch (e) { check(false, `nav / switch / back, at: ${step}`, e.message.split("\n")[0]); }
    await ctx.close();
  }

  // 5. Old links without a tenant keep working, and gain one.
  for (const [url, stored, want] of [["/po-queue/", null, "metsa"], ["/po-queue/", "studio", "studio"],
                                     ["/matching/", null, "aurora"]]) {
    const { ctx, page } = await cold(browser, url, stored);
    try {
      await page.waitForURL(/tenant=/, { timeout: TIMEOUT });
      check(param(page, "tenant") === want, `old link ${url} (stored ${stored ?? "nothing"}) → ${want}`);
    } catch (e) { check(false, `old link ${url}`, e.message.split("\n")[0]); }
    await ctx.close();
  }

  await browser.close();
  console.log(failed ? `\n${failed} failed` : "\nall deep-link cases pass");
  process.exit(failed);
}

main().catch((e) => { console.error(e); process.exit(99); });
