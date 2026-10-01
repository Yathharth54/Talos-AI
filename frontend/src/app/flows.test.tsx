import { allFlows, expectParity, FIXED_NOW, flow } from "../test/parity";
import { fixedDate, runFlowInApp } from "../test/flowHarness";
import { setReducedMotion } from "../test/media";

beforeEach(() => {
  setReducedMotion(true);
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
  vi.stubGlobal("Date", fixedDate(FIXED_NOW));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe.each(allFlows())("flow %s", (name) => {
  test("every snapshot matches the reference, region by region", async () => {
    const f = flow(name);
    const ours = await runFlowInApp(f.actions, (snapName) => Object.keys(f.snaps[snapName]?.regions ?? {}));
    expect(Object.keys(ours).sort()).toEqual(Object.keys(f.snaps).sort());
    for (const [snapName, s] of Object.entries(f.snaps)) {
      for (const [sel, html] of Object.entries(s.regions)) {
        const mine = ours[snapName]![sel] ?? null;
        if (html === null) {
          expect(mine, `${name}/${snapName} ${sel}`).toBeNull();
          continue;
        }
        try {
          expectParity(mine ?? "", html);
        } catch (err) {
          throw new Error(`${name}/${snapName} ${sel}: ${(err as Error).message}`);
        }
      }
    }
  });
});
