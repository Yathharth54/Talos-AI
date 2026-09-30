import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { extractStyle, extractTextScript, extractVaultData, readRef, REF_ASSETS } from "../scripts/reference.mjs";

const read = (p: string) => readFileSync(resolve(process.cwd(), p), "utf8").replace(/\r\n/g, "\n");

describe("verbatim copies of the reference", () => {
  const ref = readRef();

  test("styles.css equals the reference <style> block", () => {
    expect(read("src/styles.css")).toBe(extractStyle(ref));
  });

  test("reference-data.json holds the vault rows and the two tool sources verbatim", () => {
    const data = JSON.parse(read("src/demo/reference-data.json")) as {
      vaultData: unknown[];
      sources: Record<string, string>;
    };
    expect(data.vaultData).toEqual(extractVaultData(ref));
    expect(data.vaultData).toHaveLength(40);
    expect(data.sources["src-caesar"]).toBe(extractTextScript(ref, "src-caesar"));
    expect(data.sources["src-caesar"]!.split("\n")).toHaveLength(63);
    expect(data.sources["src-weather"]).toBe(extractTextScript(ref, "src-weather"));
  });

  test("the two images are byte-identical copies", () => {
    for (const f of ["apple-touch-icon.png", "hero-mark.webp"]) {
      const mine = resolve(process.cwd(), "public/assets", f);
      expect(existsSync(mine)).toBe(true);
      expect(readFileSync(mine).equals(readFileSync(resolve(REF_ASSETS, f)))).toBe(true);
    }
  });

  test("index.html carries the reference's font links and title", () => {
    const html = read("index.html");
    for (const line of ref.split("\n").slice(0, 4)) expect(html).toContain(line);
  });
});
