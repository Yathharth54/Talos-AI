import { act, render, screen } from "@testing-library/react";
import { App } from "./App";
import { Workbench } from "./app/workbench";
import { resolveMode } from "./mode";
import { createServices } from "./services";
import type { Stores } from "./store/stores";
import { setWideScreen } from "./test/media";
import { FIXED_NOW } from "./test/parity";

test("resolveMode", () => {
  expect(resolveMode("?demo", undefined)).toBe("demo");
  expect(resolveMode("", "1")).toBe("demo");
  expect(resolveMode("", undefined)).toBe("live");
});

test("demo mode shows the Demo controls; live mode doesn't", async () => {
  for (const mode of ["demo", "live"] as const) {
    // Live services need the API (app/live.test.ts): the Demo controls follow the mode alone.
    const { stores, services } = await createServices("demo");
    const { unmount } = render(<App stores={stores} workbench={new Workbench(stores, { ...services, mode })} />);
    expect(screen.getByText("Ask for something it can't do yet")).toBeInTheDocument();
    expect(screen.queryByText("Demo controls") !== null).toBe(mode === "demo");
    unmount();
  }
});

/* Carried requirements from the task 7-14 reviews. */

async function mount() {
  const { stores, services } = await createServices("demo");
  const wb = new Workbench(stores, services);
  const view = render(<App stores={stores} workbench={wb} />);
  await act(async () => {}); // the vault loads the selected tool's source
  return { stores, wb, view };
}
async function settle(stores: Stores) {
  for (let i = 0; i < 5000 && stores.ui.get().busy; i++) await act(() => vi.advanceTimersToNextTimerAsync());
}
const $ = (sel: string) => document.querySelector<HTMLElement>(sel);

describe("with fake timers", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date(FIXED_NOW));
  });
  afterEach(() => vi.useRealTimers());

  test("the composer gets focus when a run ends on a wide screen, not on a narrow one (setBusy, line 1505)", async () => {
    for (const wide of [true, false]) {
      setWideScreen(wide);
      const { stores, wb, view } = await mount();
      await act(() => wb.submit("What can you do?"));
      $("#new-session")!.focus();
      await settle(stores);
      expect(document.activeElement === $("#ask")).toBe(wide);
      view.unmount();
    }
  });
});

test("the vault view stays mounted across view switches (its swap class is per instance)", async () => {
  const { wb } = await mount();
  act(() => wb.showView("vault"));
  const detail = $("#v-detail");
  expect(detail).toHaveClass("swap");
  act(() => wb.showView("workbench"));
  act(() => wb.showView("vault"));
  expect($("#v-detail")).toBe(detail);
  expect(detail).toHaveClass("swap");
});

test("Demo controls get a stable onTogglePop: a re-render doesn't re-bind the document listeners", async () => {
  const { wb } = await mount();
  const add = vi.spyOn(document, "addEventListener");
  act(() => wb.setSpeed(2));
  act(() => wb.showView("vault"));
  expect(add.mock.calls.filter(([type]) => type === "click" || type === "keydown")).toHaveLength(0);
  act(() => wb.togglePop(true)); // popOpen is a real dependency
  expect(add.mock.calls.filter(([type]) => type === "click")).toHaveLength(1);
  add.mockRestore();
});

test("an old session with no messages shows the viewing note, never the empty-conversation text (openSession, line 2185)", async () => {
  const { stores, wb } = await mount();
  act(() =>
    stores.session.update((s) => ({
      ...s,
      sessions: [{ id: "old-empty", name: "Quiet one", started: "2026-09-29T10:00:00", live: false, runIds: [], messages: [] }, ...s.sessions],
    })),
  );
  expect($(".empty-convo")).not.toBeNull();
  act(() => wb.openSession("old-empty"));
  expect($(".viewing-note")).not.toBeNull();
  expect($(".empty-convo")).toBeNull();
});

test("an old session opens scrolled to the top; back to now scrolls to the end (lines 2191, 2202)", async () => {
  const { wb } = await mount();
  const el = $("#msgs")!;
  let top = 0;
  Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => 500 });
  Object.defineProperty(el, "scrollTop", { configurable: true, get: () => top, set: (v: number) => void (top = v) });
  act(() => wb.openSession("seed-lev"));
  expect(top).toBe(0);
  expect($(".viewing-note")).not.toBeNull();
  top = 120; // the reader scrolled down
  act(() => wb.openSession("seed-fib"));
  expect(top).toBe(0);
  top = 120;
  act(() => wb.openSession("seed-fib")); // the same session again still starts at the top
  expect(top).toBe(0);
  act(() => wb.backToNow());
  expect(top).toBe(500);
});
