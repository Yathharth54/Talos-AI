import { test, expect, type LiveApp } from "./fixtures";
import { Q } from "../support/queries";

type VaultList = { count: number; web_count: number; failed_count: number; tools: { name: string }[] };
type VaultDetail = { name: string; source: string | null; lines: number };

/** The reference's "Use in a question" presets (line 2119); other tools get `Use ${name} on `. */
const PRESETS: Record<string, string> = {
  caesar_cipher: 'Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"',
  get_current_temperature: "Use the OpenWeatherMap API to get the current temperature in Mumbai.",
};

async function vault(app: LiveApp): Promise<VaultList> {
  return (await (await app.api.get("/api/vault")).json()) as VaultList;
}

/** Forge caesar_cipher from scratch, so the vault holds at least one tool forged this session, with source. */
async function forgeCaesar(app: LiveApp): Promise<void> {
  await app.dropTool("caesar_cipher");
  await app.finished(await app.ask(Q.forge));
}

async function openVault(app: LiveApp): Promise<void> {
  await app.page.locator('.nav a[data-view="vault"]').click();
  await expect(app.page.locator("#view-vault")).toBeVisible();
}

test.describe.serial("Vault: counts, search, filters, detail, reader, remove and use", () => {
  test("counts", async ({ app, page }) => {
    await forgeCaesar(app);
    await openVault(app);
    const v = await vault(app);
    expect(v.tools.map((t) => t.name)).toContain("caesar_cipher");
    await expect(page.locator("#c-all")).toHaveText(String(v.count));
    await expect(page.locator("#c-web")).toHaveText(String(v.web_count));
    await expect(page.locator("#c-failed")).toHaveText(String(v.failed_count));
    await expect(page.locator("#v-lede")).toHaveText(`${v.count} tools, every one written and tested by Talos. Stored as .py files and a manifest.json.`);
    await expect(page.locator('tr[data-tool="caesar_cipher"] .newtag')).toHaveText("New this session");
  });

  test("search", async ({ app, page }) => {
    await openVault(app);
    const v = await vault(app);
    await page.locator("#v-search").fill("cipher");
    await expect(page.locator('tr[data-tool="caesar_cipher"]')).toBeVisible();
    const shown = await page.locator("#v-rows tr[data-tool]").count();
    await expect(page.locator("#v-count")).toHaveText(`Showing ${shown} of ${v.count}`);
    await page.locator("#v-search").fill("zzzz");
    await expect(page.locator(".v-empty")).toHaveText("No tools match. Try another word, or clear the filter.");
    await expect(page.locator("#v-count")).toHaveText(`Showing 0 of ${v.count}`);
  });

  test("filters", async ({ app, page }) => {
    await openVault(app);
    const v = await vault(app);
    for (const [filter, n] of [
      ["web", v.web_count],
      ["failed", v.failed_count],
    ] as const) {
      await page.locator(`[data-filter="${filter}"]`).click();
      await expect(page.locator(`[data-filter="${filter}"]`)).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator('[data-filter="all"]')).toHaveAttribute("aria-pressed", "false");
      await expect(page.locator("#v-rows tr[data-tool]")).toHaveCount(n);
      await expect(page.locator("#v-count")).toHaveText(`Showing ${n} of ${v.count}`);
    }
  });

  test("detail and the reader", async ({ app, page }) => {
    await openVault(app);
    const d = (await (await app.api.get("/api/vault/caesar_cipher")).json()) as VaultDetail;
    expect(d.source).not.toBeNull();

    await page.locator('[data-tool-btn="caesar_cipher"]').click();
    await expect(page.locator(".v-detail h2")).toHaveText("caesar_cipher");
    await expect(page.locator(".sigbox")).toHaveText("caesar_cipher(text: str, shift: int, mode: str) -> str");
    await expect(page.locator(".v-detail figure.code-read")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("This demo only bundles");

    const read = page.getByRole("button", { name: "Read full file" });
    const reader = page.locator(".dialog.reader");
    await read.click();
    await expect(reader.locator("h2")).toHaveText("talos/vault/tools/caesar_cipher.py");
    await expect(reader.locator("p")).toHaveText(`${d.lines} lines. Forged, tested and saved by Talos.`);
    const copy = reader.getByRole("button", { name: "Copy" });
    await copy.click();
    await expect(reader.locator('[data-r="copy"]')).toHaveText("Copied");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe((d.source ?? "").replace(/\n$/, ""));
    await page.keyboard.press("Escape");
    await expect(reader).toHaveCount(0);
    await expect(read).toBeFocused();

    await read.click();
    await expect(reader).toBeVisible();
    await page.locator("#scrim").click({ position: { x: 5, y: 5 } });
    await expect(reader).toHaveCount(0);

    await read.click();
    await expect(reader).toBeVisible();
    await reader.getByRole("button", { name: "Close" }).click();
    await expect(reader).toHaveCount(0);
  });

  test("remove from the vault", async ({ app, page }) => {
    await openVault(app);
    await page.locator('[data-tool-btn="caesar_cipher"]').click();
    const deletes: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "DELETE") deletes.push(r.url());
    });
    const remove = page.locator('[data-remove-tool="caesar_cipher"]');
    await expect(remove).toHaveText("Remove from vault");
    await remove.click();
    await expect(remove).toHaveText("Remove caesar_cipher?");
    expect(deletes).toEqual([]);

    const deleted = page.waitForResponse((r) => r.request().method() === "DELETE" && r.url().endsWith("/api/vault/caesar_cipher"));
    await remove.click();
    expect((await deleted).status()).toBe(204);
    await expect(page.locator('tr[data-tool="caesar_cipher"]')).toHaveCount(0);
    expect(await app.vaultNames()).not.toContain("caesar_cipher");
  });

  test("use in a question", async ({ app, page }) => {
    // Set-up: the last test emptied the vault of caesar_cipher, so forge it again if nothing is left.
    if (!(await vault(app)).count) await forgeCaesar(app);
    await openVault(app);
    const name = (await vault(app)).tools[0]?.name ?? "";
    expect(name).not.toBe("");
    await page.locator(`[data-tool-btn="${name}"]`).click();
    await page.locator(`[data-use-tool="${name}"]`).click();
    await expect(page.locator("#view-workbench")).toBeVisible();
    await expect(page.locator('.nav a[data-view="workbench"]')).toHaveAttribute("aria-current", "page");
    await expect(page.locator("#ask")).toHaveValue(PRESETS[name] ?? `Use ${name} on `);
  });
});
