import { test, expect, type APIRequestContext, type Page } from "@playwright/test";

/**
 * Real-browser verification of Facemetric-AI's authorization, deletion, consent, claim and logout behaviour.
 * Each test states its expected result. "UI" = driven through the real frontend in Edge; "API" = direct HTTP to the
 * backend (bypassing the frontend entirely) to prove the SERVER is authoritative.
 */
const API = "http://127.0.0.1:8100";
const PASSWORD = "correct horse battery staple";
const GHOST = "0".repeat(32); // a syntactically valid id that does not exist
const stamp = () => `${Date.now()}${Math.floor(Math.random() * 1e6)}`;

type Seed = { id: string; token: string; headline: string };

async function reset(request: APIRequestContext) {
  await request.post(`${API}/__test/reset`);
}
async function seed(request: APIRequestContext, body: { owner_email?: string; paid?: boolean; token_expired?: boolean } = {}): Promise<Seed> {
  const r = await request.post(`${API}/__test/seed`, { data: body });
  expect(r.ok()).toBeTruthy();
  return r.json();
}
async function apiSignup(request: APIRequestContext, email: string): Promise<string> {
  const r = await request.post(`${API}/api/auth/signup`, { data: { email, password: PASSWORD } });
  expect(r.status()).toBe(200);
  return (await r.json()).token;
}
async function signupUI(page: Page, email: string) {
  await page.goto("/login");
  await page.getByRole("button", { name: "Create an account" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await page.waitForURL("**/account");
}
const bearerOf = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem("aurea_token") || "null") as string | null);
const auth = (t: string) => ({ Authorization: `Bearer ${t}` });
const NOT_FOUND = "Report not found.";
const providerCalls = async (request: APIRequestContext) => (await (await request.get(`${API}/__test/provider_calls`)).json()).count as number;

test.beforeEach(async ({ request }) => reset(request));

// ----------------------------------------------------------------------------------------------- Scenario 1
test.describe("S1 correct owner", () => {
  test("S1.1 owner opens own report in the UI; report data and authorised actions are available [expect ALLOW]", async ({ page, request }) => {
    const email = `owner-${stamp()}@example.com`;
    await signupUI(page, email);
    const r = await seed(request, { owner_email: email });
    await page.goto(`/report/${r.id}`);
    await expect(page.locator("main h1").first()).toContainText(r.headline.slice(0, 25));
    await expect(page.getByText(NOT_FOUND)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Delete report" })).toBeVisible(); // authorised action offered
    const res = await request.get(`${API}/api/analyses/${r.id}`, { headers: auth((await bearerOf(page))!) });
    expect(res.status()).toBe(200);
  });

  test("S1.2 the owner's report appears in their own account list [expect ALLOW]", async ({ page, request }) => {
    const email = `owner-${stamp()}@example.com`;
    await signupUI(page, email);
    const r = await seed(request, { owner_email: email });
    const prog = await request.get(`${API}/api/me/progress`, { headers: auth((await bearerOf(page))!) });
    expect(prog.status()).toBe(200);
    expect(await prog.text()).toContain(r.id);
  });
});

// ----------------------------------------------------------------------------------------------- Scenario 2
test.describe("S2 wrong account", () => {
  test("S2.1 account B opening account A's report in the UI sees 'Report not found.' [expect 404 behaviour]", async ({ page, request }) => {
    const emailA = `a-${stamp()}@example.com`;
    await apiSignup(request, emailA);
    const r = await seed(request, { owner_email: emailA });
    await signupUI(page, `b-${stamp()}@example.com`);
    await page.goto(`/report/${r.id}`);
    await expect(page.getByText(NOT_FOUND)).toBeVisible();
    await expect(page.locator("main h1")).toHaveCount(0);
  });

  test("S2.2 API: wrong-account response is byte-identical to a nonexistent report's [expect same 404 shape]", async ({ page, request }) => {
    const emailA = `a-${stamp()}@example.com`;
    await apiSignup(request, emailA);
    const r = await seed(request, { owner_email: emailA });
    await signupUI(page, `b-${stamp()}@example.com`);
    const h = auth((await bearerOf(page))!);
    const real = await request.get(`${API}/api/analyses/${r.id}`, { headers: h });
    const ghost = await request.get(`${API}/api/analyses/${GHOST}`, { headers: h });
    expect(real.status()).toBe(404);
    expect(ghost.status()).toBe(404);
    expect(await real.text()).toBe(await ghost.text());
    expect(real.headers()["content-length"]).toBe(ghost.headers()["content-length"]);
  });

  test("S2.3 API: account B cannot delete, check out, confirm, try on, consent or rotate account A's report [expect identical 404]", async ({ page, request }) => {
    const emailA = `a-${stamp()}@example.com`;
    await apiSignup(request, emailA);
    const r = await seed(request, { owner_email: emailA, paid: true });
    await signupUI(page, `b-${stamp()}@example.com`);
    const h = auth((await bearerOf(page))!);
    const probes: [string, string, unknown?][] = [
      ["delete", `/api/analyses/${r.id}`], ["post", `/api/analyses/${r.id}/checkout`, { plan: "full" }],
      ["post", `/api/analyses/${r.id}/confirm`, {}], ["post", `/api/analyses/${r.id}/tryon`, { kind: "hair", style: "Textured quiff" }],
      ["post", `/api/analyses/${r.id}/consent/tryon`, { accept: true, provider: "fal", version: "tryon-consent-v1" }],
      ["post", `/api/analyses/${r.id}/token/rotate`, {}],
    ];
    for (const [method, path, data] of probes) {
      await reset(request);
      const real = await (request as any)[method](`${API}${path}`, { headers: h, ...(data ? { data } : {}) });
      const ghost = await (request as any)[method](`${API}${path.replace(r.id, GHOST)}`, { headers: h, ...(data ? { data } : {}) });
      expect(real.status(), `${method} ${path}`).toBe(404);
      expect(await real.text(), `${method} ${path}`).toBe(await ghost.text());
    }
    expect((await request.get(`${API}/__test/exists/${r.id}`)).ok()).toBeTruthy();
    expect((await (await request.get(`${API}/__test/exists/${r.id}`)).json()).exists).toBe(true); // nothing was deleted
    expect(await providerCalls(request)).toBe(0);
  });
});

// ----------------------------------------------------------------------------------------------- Scenario 3
test.describe("S3 anonymous report token", () => {
  async function openWithToken(page: Page, id: string, token: string | null, prefix = "facemetric_ai_rt_") {
    await page.goto("/login");
    await page.evaluate(([i, t, p]) => { if (t) localStorage.setItem(`${p}${i}`, t); }, [id, token, prefix] as [string, string | null, string]);
    await page.goto(`/report/${id}`);
  }

  test("S3.1 valid token opens the report in the UI [expect ALLOW]", async ({ page, request }) => {
    const r = await seed(request);
    await openWithToken(page, r.id, r.token, "alexendra_rt_");
    await expect(page.locator("main h1").first()).toContainText(r.headline.slice(0, 25));
  });

  test("S3.2 no token / invalid token: UI shows 'Report not found.' [expect DENY]", async ({ page, request }) => {
    const r = await seed(request);
    await openWithToken(page, r.id, null);
    await expect(page.getByText(NOT_FOUND)).toBeVisible();
    await openWithToken(page, r.id, "x".repeat(43));
    await expect(page.getByText(NOT_FOUND)).toBeVisible();
  });

  test("S3.3 API: the report id alone, or with a wrong token, is refused; the right token works [expect 404 / 404 / 200]", async ({ request }) => {
    const r = await seed(request);
    expect((await request.get(`${API}/api/analyses/${r.id}`)).status()).toBe(404);
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: { "X-Report-Token": "not-the-token" } })).status()).toBe(404);
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: { "X-Report-Token": r.token } })).status()).toBe(200);
  });

  test("S3.4 an EXPIRED token is refused in the API and the UI [expect DENY]", async ({ page, request }) => {
    const r = await seed(request, { token_expired: true });
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: { "X-Report-Token": r.token } })).status()).toBe(404);
    await openWithToken(page, r.id, r.token);
    await expect(page.getByText(NOT_FOUND)).toBeVisible();
  });

  test("S3.5 a ROTATED token revokes the old one; the new one works [expect old 404, new 200]", async ({ page, request }) => {
    const r = await seed(request);
    const rot = await request.post(`${API}/api/analyses/${r.id}/token/rotate`, { headers: { "X-Report-Token": r.token } });
    expect(rot.status()).toBe(200);
    const fresh = (await rot.json()).access_token as string;
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: { "X-Report-Token": r.token } })).status()).toBe(404);
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: { "X-Report-Token": fresh } })).status()).toBe(200);
    await openWithToken(page, r.id, r.token); // the browser still holding the OLD token
    await expect(page.getByText(NOT_FOUND)).toBeVisible();
    await openWithToken(page, r.id, fresh);
    await expect(page.locator("main h1").first()).toContainText(r.headline.slice(0, 25));
  });

  test("S3.6 only the signed-in OWNER can revoke all tokens; a token holder cannot [expect 404 then 200; token dead, owner still in]", async ({ request }) => {
    const email = `o-${stamp()}@example.com`;
    const bearer = await apiSignup(request, email);
    const r = await seed(request, { owner_email: email });
    expect((await request.delete(`${API}/api/analyses/${r.id}/token`, { headers: { "X-Report-Token": r.token } })).status()).toBe(404);
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: { "X-Report-Token": r.token } })).status()).toBe(200);
    expect((await request.delete(`${API}/api/analyses/${r.id}/token`, { headers: auth(bearer) })).status()).toBe(200);
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: { "X-Report-Token": r.token } })).status()).toBe(404);
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: auth(bearer) })).status()).toBe(200);
  });
});

// ----------------------------------------------------------------------------------------------- Scenario 4
test.describe("S4 delete", () => {
  test("S4.1 owner deletes through the UI; the report disappears and every later access is refused [expect NOT FOUND]", async ({ page, request }) => {
    const email = `owner-${stamp()}@example.com`;
    await signupUI(page, email);
    const r = await seed(request, { owner_email: email });
    const raw = await (await request.get(`${API}/__test/raw/${r.id}`)).json();
    expect(raw).toMatchObject({ exists: true, encrypted: true, has_plain_profile: false }); // encrypted at rest before deletion
    const bearer = (await bearerOf(page))!;

    await page.goto(`/report/${r.id}`);
    await expect(page.locator("main h1").first()).toContainText(r.headline.slice(0, 25));
    page.once("dialog", (d) => d.accept());
    await page.getByRole("button", { name: "Delete report" }).click();
    await page.waitForURL((u) => u.pathname === "/");

    await page.goto(`/report/${r.id}`);
    await expect(page.getByText(NOT_FOUND)).toBeVisible();
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: auth(bearer) })).status()).toBe(404);
    expect((await request.delete(`${API}/api/analyses/${r.id}`, { headers: auth(bearer) })).status()).toBe(404);
    const after = await (await request.get(`${API}/__test/raw/${r.id}`)).json();
    expect(after.exists).toBe(false); // the encrypted file and everything inside it is gone from disk
    const prog = await request.get(`${API}/api/me/progress`, { headers: auth(bearer) });
    expect(await prog.text()).not.toContain(r.id);
  });

  test("S4.2 cancelling the confirmation dialog deletes nothing [expect report still there]", async ({ page, request }) => {
    const email = `owner-${stamp()}@example.com`;
    await signupUI(page, email);
    const r = await seed(request, { owner_email: email });
    await page.goto(`/report/${r.id}`);
    await expect(page.locator("main h1").first()).toBeVisible();
    page.once("dialog", (d) => d.dismiss());
    await page.getByRole("button", { name: "Delete report" }).click();
    await page.waitForTimeout(500);
    expect((await (await request.get(`${API}/__test/exists/${r.id}`)).json()).exists).toBe(true);
  });

  test("S4.3 an anonymous token holder can delete; a stranger cannot [expect 200 / 404]", async ({ request }) => {
    const r = await seed(request);
    expect((await request.delete(`${API}/api/analyses/${r.id}`)).status()).toBe(404);
    expect((await (await request.get(`${API}/__test/exists/${r.id}`)).json()).exists).toBe(true);
    expect((await request.delete(`${API}/api/analyses/${r.id}`, { headers: { "X-Report-Token": r.token } })).status()).toBe(200);
    expect((await (await request.get(`${API}/__test/exists/${r.id}`)).json()).exists).toBe(false);
  });
});

// ----------------------------------------------------------------------------------------------- Scenario 5
test.describe("S5 try-on consent", () => {
  async function paidReport(page: Page, request: APIRequestContext) {
    const email = `owner-${stamp()}@example.com`;
    await signupUI(page, email);
    const r = await seed(request, { owner_email: email, paid: true });
    const bearer = (await bearerOf(page))!;
    return { r, bearer, email };
  }
  const tryon = (request: APIRequestContext, id: string, bearer: string) =>
    request.post(`${API}/api/analyses/${id}/tryon`, { headers: auth(bearer), data: { kind: "hair", style: "Textured quiff" } });

  test("S5.1 without consent: disclosure + 'PROVIDER POLICY UNVERIFIED' are shown, no style picker, API refuses, provider never called", async ({ page, request }) => {
    const { r, bearer } = await paidReport(page, request);
    await page.goto(`/report/${r.id}`);
    await expect(page.getByText("See your recommended styles on you")).toBeVisible();
    await expect(page.getByTestId("provider-policy-badge")).toHaveText("PROVIDER POLICY UNVERIFIED");
    await expect(page.getByText("fal.ai", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("has NOT been verified", { exact: false })).toBeVisible();
    await expect(page.getByRole("button", { name: "Textured quiff" })).toHaveCount(0);
    const res = await tryon(request, r.id, bearer);
    expect(res.status()).toBe(403);
    expect((await res.json()).detail.code).toBe("consent_required");
    expect(await providerCalls(request)).toBe(0);
  });

  test("S5.2 'No thanks' sends nothing and keeps generation blocked", async ({ page, request }) => {
    const { r, bearer } = await paidReport(page, request);
    await page.goto(`/report/${r.id}`);
    await page.getByRole("button", { name: "No thanks" }).click();
    await expect(page.getByText("your photo was not sent")).toBeVisible();
    await expect(page.getByRole("button", { name: "Textured quiff" })).toHaveCount(0);
    expect((await tryon(request, r.id, bearer)).status()).toBe(403);
    expect(await providerCalls(request)).toBe(0);
  });

  test("S5.3 agree -> picker appears -> generation works and is the ONLY provider call; consent is bound to this report + provider", async ({ page, request }) => {
    const { r, bearer, email } = await paidReport(page, request);
    await page.goto(`/report/${r.id}`);
    await page.getByRole("button", { name: /I agree/ }).click();
    const chip = page.getByRole("button", { name: "Textured quiff" });
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(page.locator('img[alt^="You with"]')).toBeVisible();
    expect(await providerCalls(request)).toBe(1);

    const rep = await (await request.get(`${API}/api/analyses/${r.id}`, { headers: auth(bearer) })).json();
    expect(rep.tryon.consent).toMatchObject({ granted: true, provider: "fal" });
    expect(rep.tryon.consent.expires_at).toBeGreaterThan(Date.now() / 1000 + 29 * 86400);

    const other = await seed(request, { owner_email: email, paid: true }); // second report of the same account
    const blocked = await tryon(request, other.id, bearer);
    expect(blocked.status()).toBe(403); // consent does not carry over to another report
    expect(await providerCalls(request)).toBe(1);
  });

  test("S5.4 withdrawal re-locks the UI and the API; no further provider calls", async ({ page, request }) => {
    const { r, bearer } = await paidReport(page, request);
    await page.goto(`/report/${r.id}`);
    await page.getByRole("button", { name: /I agree/ }).click();
    await expect(page.getByRole("button", { name: "Textured quiff" })).toBeVisible();
    await page.getByRole("button", { name: "Withdraw my consent to share my photo" }).click();
    await expect(page.getByRole("button", { name: "Textured quiff" })).toHaveCount(0);
    await expect(page.getByTestId("provider-policy-badge")).toBeVisible();
    expect((await tryon(request, r.id, bearer)).status()).toBe(403);
    expect(await providerCalls(request)).toBe(0);
  });

  test("S5.5 API-only bypass attempts (extra fields, headers, forged consent for another provider/version) all fail", async ({ page, request }) => {
    const { r, bearer } = await paidReport(page, request);
    for (const extra of [{ consent: true }, { consented: true }, { accept: true }]) {
      const res = await request.post(`${API}/api/analyses/${r.id}/tryon`, { headers: { ...auth(bearer), "X-Consent": "yes" }, data: { kind: "hair", style: "Textured quiff", ...extra } });
      expect(res.status()).toBe(403);
    }
    for (const bad of [{ provider: "gemini", version: "tryon-consent-v1" }, { provider: "fal", version: "tryon-consent-v0" }]) {
      const res = await request.post(`${API}/api/analyses/${r.id}/consent/tryon`, { headers: auth(bearer), data: { accept: true, ...bad } });
      expect(res.status()).toBe(409);
    }
    expect((await tryon(request, r.id, bearer)).status()).toBe(403);
    expect(await providerCalls(request)).toBe(0);
  });

  test("S5.6 unauthenticated and wrong-account try-on never reach the provider", async ({ page, request }) => {
    const { r } = await paidReport(page, request);
    const stranger = await apiSignup(request, `s-${stamp()}@example.com`);
    expect((await request.post(`${API}/api/analyses/${r.id}/tryon`, { data: { kind: "hair", style: "Textured quiff" } })).status()).toBe(404);
    expect((await tryon(request, r.id, stranger)).status()).toBe(404);
    expect(await providerCalls(request)).toBe(0);
  });
});

// ----------------------------------------------------------------------------------------------- Scenario 6
test.describe("S6 claim", () => {
  test("S6.1 UI: signed-in user holding the token saves the report to their account [expect valid claim]", async ({ page, request }) => {
    await signupUI(page, `c-${stamp()}@example.com`);
    const r = await seed(request);
    await page.evaluate(([i, t]) => localStorage.setItem(`facemetric_ai_rt_${i}`, t), [r.id, r.token]);
    await page.goto(`/report/${r.id}`);
    const save = page.getByRole("button", { name: "Save to my progress" });
    await expect(save).toBeVisible();
    // The button renames itself to "Saving..." while the request is in flight, so "button gone" is NOT proof the claim finished.
    // Wait for the claim response itself (a race here made this test intermittent under load) and require it to be 200.
    const claimed = page.waitForResponse((res) => res.url().includes("/claim") && res.request().method() === "POST");
    await save.click();
    expect((await claimed).status()).toBe(200);
    await expect(save).toHaveCount(0); // saved
    const bearer = (await bearerOf(page))!;
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: auth(bearer) })).status()).toBe(200); // session alone now suffices
  });

  test("S6.2 API claim matrix: no token, bad token, valid, replay, other account, anonymous", async ({ request }) => {
    const a = await apiSignup(request, `a-${stamp()}@example.com`);
    const b = await apiSignup(request, `b-${stamp()}@example.com`);
    const r = await seed(request);
    const claim = (h: Record<string, string>) => request.post(`${API}/api/me/analyses/${r.id}/claim`, { headers: h });
    expect((await claim(auth(a))).status()).toBe(404); // id + session is not enough
    expect((await claim({ ...auth(a), "X-Report-Token": "bad" })).status()).toBe(404);
    expect((await request.post(`${API}/api/me/analyses/${r.id}/claim`, { headers: { "X-Report-Token": r.token } })).status()).toBe(401); // token but not signed in
    expect((await claim({ ...auth(a), "X-Report-Token": r.token })).status()).toBe(200); // valid claim
    expect((await claim({ ...auth(a), "X-Report-Token": r.token })).status()).toBe(200); // replay by the same owner: idempotent
    expect((await claim({ ...auth(b), "X-Report-Token": r.token })).status()).toBe(403); // token holder, but already owned by A
    expect((await claim(auth(b))).status()).toBe(404); // without the token B learns nothing
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: auth(a) })).status()).toBe(200);
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: auth(b) })).status()).toBe(404); // ownership unchanged
  });
});

// ----------------------------------------------------------------------------------------------- Scenario 7
test.describe("S7 browser credential behaviour", () => {
  test("S7.1 credentials are attached to protected requests (session for owners, token for anonymous)", async ({ page, request }) => {
    const email = `owner-${stamp()}@example.com`;
    await signupUI(page, email);
    const owned = await seed(request, { owner_email: email });
    const seen: Record<string, string>[] = [];
    page.on("request", (q) => { if (q.url().includes(`/api/analyses/${owned.id}`)) seen.push(q.headers()); });
    await page.goto(`/report/${owned.id}`);
    await expect(page.locator("main h1").first()).toBeVisible();
    expect(seen.some((h) => (h["authorization"] ?? "").startsWith("Bearer "))).toBe(true);

    const anon = await seed(request);
    const ctx2 = await page.context().browser()!.newContext({ baseURL: "http://127.0.0.1:3100" });
    const p2 = await ctx2.newPage();
    const seen2: Record<string, string>[] = [];
    p2.on("request", (q) => { if (q.url().includes(`/api/analyses/${anon.id}`)) seen2.push(q.headers()); });
    await p2.goto("/login");
    await p2.evaluate(([i, t]) => localStorage.setItem(`facemetric_ai_rt_${i}`, t), [anon.id, anon.token]);
    await p2.goto(`/report/${anon.id}`);
    await expect(p2.locator("main h1").first()).toBeVisible();
    expect(seen2.some((h) => h["x-report-token"] === anon.token)).toBe(true);
    expect(seen2.some((h) => (h["authorization"] ?? "") !== "")).toBe(false);
    await ctx2.close();
  });

  test("S7.2 logout clears client state, protected pages bounce to login, the old session is revoked on the server", async ({ page, request }) => {
    const email = `owner-${stamp()}@example.com`;
    await signupUI(page, email);
    const r = await seed(request, { owner_email: email });
    const oldToken = (await bearerOf(page))!;
    const oldUser = await page.evaluate(() => localStorage.getItem("aurea_user"));
    await page.getByRole("button", { name: "Sign out" }).click();
    // Observed: the app ends on /login?next=/account (the account page's "no user" redirect wins a race against the
    // button's router.push("/")). Either landing is acceptable; what matters is that the client state is gone.
    await page.waitForURL((u) => u.pathname === "/" || u.pathname === "/login");
    expect(await bearerOf(page)).toBeNull();
    await page.goto("/account");
    await page.waitForURL((u) => u.pathname === "/login");
    // server side: the token that was valid a moment ago is dead
    expect((await request.get(`${API}/api/me`, { headers: auth(oldToken) })).status()).toBe(401);
    expect((await request.get(`${API}/api/analyses/${r.id}`, { headers: auth(oldToken) })).status()).toBe(404);

    // stale credentials re-injected into the browser cannot bypass the server
    await page.evaluate(([t, u]) => { localStorage.setItem("aurea_token", JSON.stringify(t)); localStorage.setItem("aurea_user", u!); }, [oldToken, oldUser]);
    await page.goto("/account");
    await page.waitForURL((u) => u.pathname === "/login");
    await page.goto(`/report/${r.id}`);
    await expect(page.getByText(NOT_FOUND)).toBeVisible();
  });

  test("S7.3 direct API: protected account routes refuse requests with no or garbage credentials [expect 401]", async ({ request }) => {
    for (const path of ["/api/me", "/api/me/progress"]) {
      expect((await request.get(`${API}${path}`)).status(), path).toBe(401);
      expect((await request.get(`${API}${path}`, { headers: { Authorization: "Bearer not-a-real-token" } })).status(), path).toBe(401);
      expect((await request.get(`${API}${path}`, { headers: { Authorization: "Bearer abcd.efgh" } })).status(), path).toBe(401);
    }
  });

  test("S7.4 an expired server session is refused although the browser still holds it", async ({ page, request }) => {
    const email = `owner-${stamp()}@example.com`;
    await signupUI(page, email);
    const r = await seed(request, { owner_email: email });
    await page.goto(`/report/${r.id}`);
    await expect(page.locator("main h1").first()).toBeVisible();
    // The browser keeps its token; log the same account out from another client so the session is revoked server side.
    const tok = (await bearerOf(page))!;
    await request.post(`${API}/api/auth/logout`, { headers: auth(tok) });
    await page.reload();
    await expect(page.getByText(NOT_FOUND)).toBeVisible();
  });
});
