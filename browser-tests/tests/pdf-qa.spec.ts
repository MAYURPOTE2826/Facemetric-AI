import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Print / PDF QA for the hair section. Generates real PDFs from the app's print view (Chromium only - page.pdf needs it) into results/pdf-qa/
 * for a human to inspect, and asserts the mechanical things: the section is in the printed page, every image loaded, nothing overflows horizontally,
 * the crown state and confidence rows are present. The seeded hair data is SYNTHETIC; this checks layout, not accuracy.
 */
const API = "http://127.0.0.1:8100";
const OUT = path.join(__dirname, "..", "results", "pdf-qa");

async function seed(request: APIRequestContext, body: Record<string, unknown>) {
  const r = await request.post(`${API}/__test/seed`, { data: body });
  expect(r.ok()).toBeTruthy();
  return r.json() as Promise<{ id: string; token: string }>;
}

async function printPdf(page: Page, s: { id: string; token: string }, name: string) {
  await page.goto("/login");
  await page.evaluate(([i, t]) => localStorage.setItem(`facemetric_ai_rt_${i}`, t), [s.id, s.token] as [string, string]);
  await page.goto(`/report/${s.id}/print`);
  await expect(page.getByTestId("hair-analysis")).toBeVisible({ timeout: 40000 });
  await page.emulateMedia({ media: "print" });
  await page.waitForFunction(() => Array.from(document.images).every((i) => i.complete));
  const bad = await page.evaluate(() => Array.from(document.images).filter((i) => !i.naturalWidth).map((i) => i.alt || i.src.slice(0, 40)));
  expect(bad, "images that failed to load").toEqual([]);
  fs.mkdirSync(OUT, { recursive: true });
  const file = path.join(OUT, `${name}.pdf`);
  await page.pdf({ path: file, format: "A4", printBackground: true, margin: { top: "12mm", bottom: "12mm", left: "10mm", right: "10mm" } });
  return file;
}

test.beforeEach(async ({ request }) => { await request.post(`${API}/__test/reset`); });

test.describe("P print / PDF of the hair section", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "page.pdf is Chromium-only");

  test("P1 front-only report prints: hair section, overlay, legend, confidence rows, crown NOT ASSESSABLE, limitations; no overflow", async ({ page, request }) => {
    const file = await printPdf(page, await seed(request, { hair: "ok", paid: true }), "hair-front-only");
    expect(fs.statSync(file).size).toBeGreaterThan(20000);
    const sec = page.getByTestId("hair-analysis");
    await expect(page.getByTestId("hair-crown")).toContainText("NOT ASSESSABLE");
    await expect(page.getByTestId("hair-legend")).toBeVisible();
    await expect(page.getByTestId("hair-limitations")).toContainText("NOT MEASURED");
    expect(await page.getByText(/confidence/i).count()).toBeGreaterThan(5); // each row shows its confidence
    const overflow = await sec.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    const noPrint = await page.evaluate(() => Array.from(document.querySelectorAll(".no-print")).every((e) => getComputedStyle(e).display === "none"));
    expect(noPrint).toBe(true);
  });

  test("P2 front + top report prints with the crown assessed", async ({ page, request }) => {
    await printPdf(page, await seed(request, { hair: "front_top", paid: true }), "hair-front-top");
    await expect(page.getByTestId("hair-crown")).not.toContainText("NOT ASSESSABLE");
  });

  test("P3 hidden hairline and engine-error reports print as inconclusive (no reassuring text in the PDF view)", async ({ page, request }) => {
    for (const kind of ["hidden", "engine_error"]) {
      await request.post(`${API}/__test/reset`);
      await printPdf(page, await seed(request, { hair: kind, paid: true }), `hair-${kind}`);
      const text = (await page.getByTestId("hair-analysis").innerText()).toLowerCase();
      for (const bad of ["no obvious recession", "no reduced visible density", "healthy hair", "no hair loss", "hair score"]) expect(text).not.toContain(bad);
    }
  });
});
