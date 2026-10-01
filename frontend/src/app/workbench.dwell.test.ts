import { createServices } from "../services";
import type { PlayerOptions } from "../transport/player";
import { Workbench } from "./workbench";

const seen = vi.hoisted(() => [] as { momentDwell: boolean }[]);
vi.mock("../transport/player", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../transport/player")>();
  class Recording extends mod.Player {
    constructor(...args: ConstructorParameters<typeof mod.Player>) {
      super(...args);
      seen.push({ momentDwell: (args[1] as PlayerOptions).momentDwell });
    }
  }
  return { ...mod, Player: Recording };
});

beforeEach(() => void (seen.length = 0));

test("the §6 moment dwells follow the transport: off for DemoTransport, on for any other, whatever the mode", async () => {
  for (const mode of ["demo", "live"] as const) {
    // Live services need the API (app/live.test.ts covers their dwells): here the mode alone changes.
    const { stores, services } = await createServices("demo");
    const wb = new Workbench(stores, { ...services, mode });
    await wb.submit("What can you do?");
    await wb.stop();
  }
  expect(seen.map((s) => s.momentDwell)).toEqual([false, false]);

  const { stores, services } = await createServices("demo");
  const wb = new Workbench(stores, { ...services, demo: null });
  await wb.submit("What can you do?");
  await wb.stop();
  expect(seen.at(-1)!.momentDwell).toBe(true);
});
