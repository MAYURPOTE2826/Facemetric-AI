import { test, expect, type APIRequestContext } from "@playwright/test";

/**
 * Browser verification of the hair-analysis UI added after the original 26 tests: the report section, the capture-flow explainer,
 * and the owner's "clear all my progress" button. The seeded hair data is a SYNTHETIC drawn head run through the real engine:
 * this checks what the page RENDERS, not whether the engine is accurate.
 */
const API = "http://127.0.0.1:8100";
const PASSWORD = "correct horse battery staple";
const stamp = () => `${Date.now()}${Math.floor(Math.random() * 1e6)}`;

async function seed(request: APIRequestContext, body: Record<string, unknown>) {
  const r = await request.post(`${API}/__test/seed`, { data: body });
  expect(r.ok()).toBeTruthy();
  return r.json() as Promise<{ id: string; token: string }>;
}

test.beforeEach(async ({ request }) => { await request.post(`${API}/__test/reset`); });

test.describe("H hair analysis UI", () => {
  test("H1 report shows the screening section: confidence, NOT ASSESSABLE crown, legend, limitations, no old score, no cm/mm", async ({ page, request }) => {
    const s = await seed(request, { hair: true });
    await page.goto("/login");
    await page.evaluate(([i, t]) => localStorage.setItem(`facemetric_ai_rt_${i}`, t), [s.id, s.token] as [string, string]);
    await page.goto(`/report/${s.id}`);
    const sec = page.getByTestId("hair-analysis");
    await expect(sec).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId("hair-crown")).toContainText("NOT ASSESSABLE");
    await expect(page.getByTestId("hair-temple-left")).toContainText("Possible recession pattern");
    await expect(page.getByTestId("hair-legend")).toContainText("Grey: not assessable");
    await expect(page.getByTestId("hair-limitations")).toContainText("NOT MEASURED");
    await expect(page.getByTestId("hair-quality")).toContainText("confidence");
    const overlay = page.getByRole("img", { name: "Hairline analysis" });
    await expect(overlay).toBeVisible();
    expect(await overlay.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(50); // the overlay image really loaded
    const text = (await sec.innerText()).toLowerCase();
    for (const bad of ["hair score", " cm", " mm", "alopecia", "healthy hair", "no hair loss", "minoxidil"]) expect(text).not.toContain(bad);
  });

  test("H2 the capture page explains front vs top photo without needing the hair questionnaire", async ({ page }) => {
    await page.goto("/analyze");
    await page.getByRole("spinbutton").fill("30"); // Age
    await page.getByRole("button", { name: "Male", exact: true }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByTestId("hair-capture-explainer")).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId("hair-capture-explainer")).toContainText("Top-of-head photo → crown and parting");
  });

  test("H3 'Clear all my progress': cancelling deletes nothing; confirming with DELETE removes the account's reports", async ({ page, request }) => {
    const email = `h3-${stamp()}@example.test`;
    await page.goto("/login");
    await page.getByRole("button", { name: "Create an account" }).click();
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Create account", exact: true }).click();
    await page.waitForURL("**/account");
    const s = await seed(request, { owner_email: email });
    await page.goto("/account");
    const btn = page.getByTestId("clear-progress");
    await expect(btn).toBeVisible({ timeout: 30000 });
    const queue: string[] = [];
    page.on("dialog", (d) => { const a = queue.shift(); if (a === undefined || a === "dismiss") void d.dismiss(); else void d.accept(a === "ok" ? undefined : a); });
    const exists = async () => ((await (await request.get(`${API}/__test/exists/${s.id}`)).json()) as { exists: boolean }).exists;
    queue.push("dismiss"); // cancel the first confirmation -> nothing happens
    await btn.click();
    expect(await exists()).toBe(true);
    queue.push("ok", "nope"); // confirm, then type the wrong word -> nothing happens
    await btn.click();
    expect(await exists()).toBe(true);
    queue.push("ok", "DELETE"); // confirm and type DELETE -> reports are gone
    await btn.click();
    await expect.poll(exists, { timeout: 15000 }).toBe(false);
  });

  const REASSURANCE = ["no obvious recession", "no reduced visible density", "hair score", "healthy hair", "no hair loss"];
  async function openReport(page: import("@playwright/test").Page, s: { id: string; token: string }) {
    await page.goto("/login");
    await page.evaluate(([i, t]) => localStorage.setItem(`facemetric_ai_rt_${i}`, t), [s.id, s.token] as [string, string]);
    await page.goto(`/report/${s.id}`);
  }

  test("H4 hidden hairline (fringe): inconclusive, retake advice, and NO reassuring wording", async ({ page, request }) => {
    await openReport(page, await seed(request, { hair: "hidden" }));
    const sec = page.getByTestId("hair-analysis");
    await expect(sec).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId("hair-hairline")).toContainText("Not reliably visible");
    await expect(page.getByTestId("hair-temple-left")).toContainText("Not assessable");
    await expect(page.getByTestId("hair-guidance")).toContainText("Retake");
    const text = (await sec.innerText()).toLowerCase();
    for (const bad of REASSURANCE) expect(text).not.toContain(bad);
  });

  test("H5 engine error: shows inconclusive, never a healthy-hair result", async ({ page, request }) => {
    await openReport(page, await seed(request, { hair: "engine_error" }));
    const sec = page.getByTestId("hair-analysis");
    await expect(sec).toBeVisible({ timeout: 30000 });
    await expect(sec).toContainText("inconclusive");
    await expect(page.getByTestId("hair-crown")).toContainText("NOT ASSESSABLE");
    const text = (await sec.innerText()).toLowerCase();
    for (const bad of REASSURANCE) expect(text).not.toContain(bad);
  });

  test("H6 front + top photo: crown is shown as assessed with its own confidence (not NOT ASSESSABLE)", async ({ page, request }) => {
    await openReport(page, await seed(request, { hair: "front_top" }));
    await expect(page.getByTestId("hair-analysis")).toBeVisible({ timeout: 30000 });
    const crown = page.getByTestId("hair-crown");
    await expect(crown).not.toContainText("NOT ASSESSABLE");
    await expect(crown).toContainText("confidence");
  });

  test("H7 legacy report without hair.analysis still renders; the new section is simply absent (no crash)", async ({ page, request }) => {
    await openReport(page, await seed(request, { hair: "legacy" }));
    await expect(page.locator("main h1").first()).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId("hair-analysis")).toHaveCount(0);
    await expect(page.getByText("Application error")).toHaveCount(0);
  });

  async function ownerWithTwoReports(page: import("@playwright/test").Page, request: APIRequestContext, second: string) {
    const email = `h8-${stamp()}@example.test`;
    await page.goto("/login");
    await page.getByRole("button", { name: "Create an account" }).click();
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Create account", exact: true }).click();
    await page.waitForURL("**/account");
    await seed(request, { owner_email: email, hair: "ok" });
    await seed(request, { owner_email: email, hair: second });
    await page.goto("/account");
  }

  test("H8a progress page: two comparable hair results -> 'no change beyond normal variation' wording, no progression claim", async ({ page, request }) => {
    await ownerWithTwoReports(page, request, "ok");
    const r = page.getByTestId("hair-longitudinal-result");
    await expect(r).toBeVisible({ timeout: 30000 });
    await expect(r).toContainText("No change beyond normal photo-to-photo variation");
    await expect(r).toContainText("unvalidated");
  });

  test("H8b progress page: a hidden hairline in one photo -> comparison REFUSED with a reason, no change claimed", async ({ page, request }) => {
    await ownerWithTwoReports(page, request, "hidden");
    const r = page.getByTestId("hair-longitudinal-result");
    await expect(r).toBeVisible({ timeout: 30000 });
    await expect(r).toContainText("Not compared");
    const text = (await r.innerText()).toLowerCase();
    expect(text).not.toContain("no change beyond");
    expect(text).not.toContain("measurable change");
  });
});
