import { act, fireEvent, render } from "@testing-library/react";
import { App } from "../App";
import { Workbench } from "../app/workbench";
import { createServices } from "../services";
import type { FlowAction } from "./parity";

type Regions = Record<string, string | null>;

const VIEWS = ["workbench", "vault", "sessions", "settings"];

/**
 * The generator pins the clock with Playwright's `clock.setFixedTime`: `Date` always reads FIXED_NOW
 * while timers still run. Faking `Date` with the timers would advance it, so the harness instead stubs
 * `Date` with one whose "now" never moves (session ids like `s1-<Date.now()>` depend on it).
 */
export function fixedDate(iso: string): DateConstructor {
  const at = new Date(iso).getTime();
  class FixedDate extends Date {
    constructor(...args: unknown[]) {
      if (args.length === 0) super(at);
      else super(...(args as [string | number | Date]));
    }
    static override now(): number {
      return at;
    }
  }
  return FixedDate as DateConstructor;
}

const evalCond = (cond: string): boolean => Boolean(new Function(`return (${cond});`)());
const el = (sel: string): HTMLElement => {
  const e = document.querySelector<HTMLElement>(sel);
  if (!e) throw new Error(`no element ${sel}`);
  return e;
};
const grab = (sels: string[]): Regions => Object.fromEntries(sels.map((s) => [s, document.querySelector(s)?.outerHTML ?? null]));

/**
 * Replays a reference flow against the app in demo mode and returns its snapshots, keyed by snapshot
 * name then region selector. Mirrors the fixture generator's semantics (Task 2); callers install fake
 * timers at FIXED_NOW and reduced motion first.
 */
export async function runFlowInApp(actions: FlowAction[], regionsFor: (name: string) => string[]): Promise<Record<string, Regions>> {
  window.location.hash = "";
  const { stores, services } = await createServices("demo");
  const host = document.body.appendChild(document.createElement("div"));
  const view = render(<App stores={stores} workbench={new Workbench(stores, services)} />, { container: host });
  await act(async () => {});
  const snaps: Record<string, Regions> = {};
  const hooks: { cond: string; name?: string; click?: string[]; done: boolean }[] = [];

  const fireHooks = async () => {
    for (const h of hooks) {
      if (h.done || !evalCond(h.cond)) continue;
      h.done = true;
      if (h.name) snaps[h.name] = grab(regionsFor(h.name));
      for (const sel of h.click ?? []) await act(async () => el(sel).click());
    }
  };
  const until = async (cond: () => boolean) => {
    for (let i = 0; i < 20000; i++) {
      await fireHooks();
      if (cond()) return;
      if (vi.getTimerCount() === 0) throw new Error("flow stuck: no timers left and the condition is false");
      await act(() => vi.advanceTimersToNextTimerAsync());
    }
    throw new Error("flow did not settle");
  };

  // A click that sets location.hash (openSession, "Open in vault"...) changes the view on hashchange. The
  // reference's page handles that event before Playwright looks again; jsdom fires it from a timer, so
  // it has to land before the next action, check or snapshot.
  const viewShown = () => {
    const h = window.location.hash.slice(1);
    return !h || !document.getElementById(`view-${VIEWS.includes(h) ? h : "workbench"}`)?.hidden;
  };

  try {
    for (const a of actions) {
      switch (a.do) {
        case "submit":
          await act(async () => void fireEvent.change(el("#ask"), { target: { value: a.text } }));
          await act(async () => void fireEvent.submit(el("#composer")));
          break;
        case "click":
          await act(async () => el(a.sel).click());
          break;
        case "fill":
          await act(async () => void fireEvent.change(el(a.sel), { target: { value: a.value } }));
          break;
        case "key":
          await act(async () => void fireEvent.keyDown(document.activeElement ?? document.body, { key: a.key }));
          break;
        case "hash": {
          const name = a.value.slice(1);
          await act(async () => {
            window.location.hash = a.value;
          });
          await until(() => !document.getElementById(`view-${name}`)?.hidden);
          break;
        }
        case "until":
          await until(() => evalCond(a.cond));
          break;
        case "snap":
          snaps[a.name] = grab(regionsFor(a.name));
          break;
        case "snapAt":
          hooks.push({ cond: a.cond, name: a.name, done: false });
          break;
        case "at":
          hooks.push({ cond: a.cond, click: a.click, done: false });
          break;
      }
      if (!viewShown()) await until(viewShown);
      await fireHooks();
    }
  } finally {
    view.unmount();
    host.remove();
  }
  return snaps;
}
