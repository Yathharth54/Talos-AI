import { test, expect, type LiveApp } from "./fixtures";
import { Q } from "../support/queries";

type SessionSummary = { id: string; name: string; run_count: number };
type SessionDetail = { session: { id: string; name: string }; runs: { n: number; query: string; status: string }[] };

async function sessions(app: LiveApp): Promise<SessionSummary[]> {
  return (await (await app.api.get("/api/sessions")).json()) as SessionSummary[];
}

/** The i-th session of `GET /api/sessions` (newest first); fails the test when there isn't one. */
async function nth(app: LiveApp, i: number): Promise<SessionSummary> {
  const s = (await sessions(app))[i];
  if (!s) throw new Error(`GET /api/sessions has no session at ${i}`);
  return s;
}

async function detail(app: LiveApp, id: string): Promise<SessionDetail> {
  return (await (await app.api.get(`/api/sessions/${id}`)).json()) as SessionDetail;
}

/** Forge caesar_cipher from scratch in the current session, then reuse it: two finished runs. */
async function forgeAndReuse(app: LiveApp): Promise<void> {
  await app.dropTool("caesar_cipher");
  await app.finished(await app.ask(Q.forge));
  await app.finished(await app.ask(Q.reuse));
}

test.describe.serial("Sessions: boot, new session, the Sessions page, old sessions and reload", () => {
  test("boot opens the newest session", async ({ app, page }) => {
    // Set-up: the current session gets a finished run, so there is a session with runs whatever ran before.
    await app.dropTool("caesar_cipher");
    await app.finished(await app.ask(Q.forge));
    await page.reload();
    await expect(page.locator("body")).not.toHaveClass(/booting/);
    await expect(page.locator("#session-title")).toHaveText((await nth(app, 0)).name);
  });

  test("an empty session is reused", async ({ app, page }) => {
    const withRuns = await nth(app, 0);
    await expect(page.locator("#session-title")).toHaveText(withRuns.name);

    const created = page.waitForResponse((r) => r.url().endsWith("/api/sessions") && r.request().method() === "POST");
    await page.locator("#new-session").click();
    const empty = (await (await created).json()) as { id: string; name: string };
    expect(empty.id).not.toBe(withRuns.id);
    await expect(page.locator("#session-title")).toHaveText(empty.name);
    await expect(page.locator(".empty-convo")).toBeVisible();

    const again = page.waitForResponse((r) => r.url().endsWith("/api/sessions") && r.request().method() === "POST");
    await page.locator("#new-session").click();
    const reused = (await (await again).json()) as { id: string; name: string };
    expect(reused.id).toBe(empty.id);
    await expect(page.locator("#session-title")).toHaveText(empty.name);
    expect((await sessions(app)).map((s) => s.id)).not.toContain(empty.id);

    await page.reload();
    await expect(page.locator("body")).not.toHaveClass(/booting/);
    await expect(page.locator("#session-title")).toHaveText(withRuns.name);
  });

  test("the Sessions page", async ({ app, page }) => {
    // Set-up: move to a new session and give it two runs, so the old session is the previous one.
    const previous = await nth(app, 0);
    const created = page.waitForResponse((r) => r.url().endsWith("/api/sessions") && r.request().method() === "POST");
    await page.locator("#new-session").click();
    const current = (await (await created).json()) as { id: string; name: string };
    await expect(page.locator("#session-title")).toHaveText(current.name);
    await forgeAndReuse(app);

    await page.locator('.nav a[data-view="sessions"]').click();
    const today = page.locator("section.day").first();
    await expect(today.locator("h2")).toHaveText("Today");

    const list = await sessions(app);
    expect(list.map((s) => s.id).slice(0, 2)).toEqual([current.id, previous.id]);
    // Only sessions with runs are listed, and the current one has runs: no other empty session gets a card.
    await expect(page.locator("article.sess")).toHaveCount(list.length);
    await expect(page.locator("article.sess .sess-empty")).toHaveCount(0);

    // A session is renamed after its first run (and both are about the Caesar cipher), so cards are found by id.
    const card = (id: string) => page.locator("article.sess", { has: page.locator(`[data-open-session="${id}"]`) });
    const cur = card(current.id);
    await expect(cur.locator("h3")).toHaveText((await nth(app, 0)).name);
    await expect(cur.locator(".live")).toHaveText("Now");
    await expect(cur.getByRole("button")).toHaveText("Continue");

    const prev = card(previous.id);
    await expect(prev.locator("h3")).toHaveText((await nth(app, 1)).name);
    const prevRuns = (await detail(app, previous.id)).runs.slice().sort((a, b) => a.n - b.n);
    await expect(prev.locator(".live")).toHaveCount(0);
    await expect(prev.getByRole("button")).toHaveText("Open");
    await expect(prev.locator(".when span").first()).toHaveText(new RegExp(`^${prevRuns.length} ${prevRuns.length === 1 ? "run" : "runs"}(, \\d+ forged)?$`));
    await expect(prev.locator("ol li:not(.muted)")).toHaveText(prevRuns.slice(0, 3).map((r) => r.query));
  });

  test("open an old session, then back to now", async ({ app, page }) => {
    const [current, previous] = [await nth(app, 0), await nth(app, 1)];
    await expect(page.locator("#session-title")).toHaveText(current.name);

    await page.locator('.nav a[data-view="sessions"]').click();
    await page.locator(`[data-open-session="${previous.id}"]`).click();
    await expect(page.locator("#view-workbench")).toBeVisible();
    await expect(page.locator("#session-title")).toHaveText(previous.name);
    await expect(page.locator(".viewing-note")).toHaveText(/^.+, .+\. Read only\.$/);
    await expect(page.locator("#back-session")).toBeVisible();
    await expect(page.locator("#new-session")).toBeHidden();
    await expect(page.locator("#ask")).toBeDisabled();
    await expect(page.locator("#send")).toBeDisabled();
    await expect(page.locator("#composer-hint")).toHaveText(`Viewing an old session. Go back to ${current.name} to ask something.`);
    await expect(page.locator(".node.answer")).toBeVisible();

    await page.locator("#back-session").click();
    await expect(page.locator("#ask")).toBeEnabled();
    await expect(page.locator("#send")).toBeEnabled();
    await expect(page.locator("#composer-hint")).toHaveText("Enter to send, Shift+Enter for a new line");
    await expect(page.locator("#session-title")).toHaveText(current.name);
  });

  test("reload keeps the conversation", async ({ app, page }) => {
    const current = await nth(app, 0);
    await expect(page.locator("#session-title")).toHaveText(current.name);
    const finished = (await detail(app, current.id)).runs.filter((r) => /^(done|failed|stopped|declined)$/.test(r.status)).sort((a, b) => a.n - b.n);
    expect(finished.length).toBeGreaterThanOrEqual(2);
    await expect(page.locator(".run-link")).toHaveCount(finished.length);
    const msgs = await page.locator(".msg").count();

    await page.reload();
    await expect(page.locator("body")).not.toHaveClass(/booting/);
    await expect(page.locator("#session-title")).toHaveText(current.name);
    await expect(page.locator(".msg")).toHaveCount(msgs);
    await expect(page.locator(".run-link")).toHaveCount(finished.length);
    const last = page.locator(".run-link").last();
    await expect(last).toHaveAttribute("aria-current", "true");

    // The first run is the forge: its bench shows the tool's signature and the forge strip, finished.
    const first = page.locator(".run-link").first();
    await first.click();
    await expect(first).toHaveAttribute("aria-current", "true");
    await expect(last).toHaveAttribute("aria-current", "false");
    await expect(page.locator("#b-sig")).toContainText("caesar_cipher");
    await expect(page.locator('#b-strip [data-node="forger"]')).toHaveClass(/\bforge\b/);
    await expect(page.locator('#b-strip [data-node="answer"]')).toHaveClass(/\banswer\b/);
    await expect(page.locator('#b-strip [data-node="vault"]')).toHaveCount(0);
  });
});
