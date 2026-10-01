import { fireEvent, render, screen } from "@testing-library/react";
import { allFlows, expectParity, fixtureCase, flow } from "../../test/parity";
import { asRun } from "../../test/parity/runs";
import { setReducedMotion } from "../../test/media";
import { innerOf, ssr } from "../../test/ssr";
import type { Run } from "../../store/types";
import { Banner } from "./Banner";
import { Bench } from "./Bench";
import { Idle } from "./Idle";
import { Strip } from "./Strip";
import { Tabs } from "./Tabs";

const noop = () => {};
const pureSnaps = () => allFlows().flatMap((f) => Object.entries(flow(f).snaps).filter(([, s]) => s.pure).map(([n, s]) => [`${f}/${n}`, s] as const));

test.each(["strip/forge-pending", "strip/forge-planner-active", "strip/forge-retry", "strip/forge-failed", "strip/vault", "strip/primitive-waiting", "strip/chat", "strip/stopped"])(
  "%s",
  (id) => {
    const c = fixtureCase(id);
    expectParity(innerOf(ssr(<Strip run={asRun(c.state.run)} />)), c.html!);
  },
);

test.each(["banner/saved", "banner/removed", "banner/none"])("%s", (id) => {
  const c = fixtureCase(id);
  expectParity(ssr(<Banner banner={asRun(c.state.run).banner} />), c.html!);
});

test.each(["tabs/log-only", "tabs/forge"])("%s", (id) => {
  const c = fixtureCase(id);
  expectParity(ssr(<Tabs run={asRun(c.state.run)} onSelect={noop} />), c.html!);
});

test("strip, banner and tabs match every flow checkpoint", () => {
  const snaps = pureSnaps();
  expect(snaps.length).toBeGreaterThan(30);
  for (const [, s] of snaps) {
    const run = asRun(s.run);
    expectParity(innerOf(ssr(<Strip run={run} />)), s.pure!.strip);
    expectParity(ssr(<Banner banner={run.banner} />), s.pure!.banner);
    expectParity(ssr(<Tabs run={run} onSelect={noop} />), s.pure!.tabs);
  }
});

/** Empties #b-panel: the panel itself is Task 9's and is compared there. */
const withoutPanel = (html: string) => {
  const t = document.createElement("template");
  t.innerHTML = html;
  t.content.querySelector("#b-panel")!.innerHTML = "";
  return t.innerHTML;
};

test.each(["bench/planning", "bench/chat-done"])("%s (renderBench)", (id) => {
  const c = fixtureCase(id);
  const run = asRun(c.state.run);
  const html = ssr(<Bench run={run} live={c.state.live as boolean} panel={null} onTab={noop} onStop={noop} onOpenTool={noop} />);
  expectParity(withoutPanel(html), withoutPanel(c.html!));
});

test.each(["idle/default", "idle/key-set-ask-off"])("%s (renderIdle)", (id) => {
  const c = fixtureCase(id);
  const s = c.state as { count: number; env: Record<string, string>; askExec: boolean };
  expectParity(ssr(<Idle count={s.count} weatherKeySet={!!s.env.OPENWEATHERMAP_API_KEY} askExec={s.askExec} onSuggest={noop} />), c.html!);
});

test("the idle bench keeps what renderIdle() wrote until it's drawn again (python-no-ask flow)", () => {
  const { container, rerender } = render(<Idle count={40} weatherKeySet={false} askExec onSuggest={noop} />);
  rerender(<Idle count={39} weatherKeySet askExec={false} onSuggest={noop} />);
  expect(container.querySelector(".setup-line")?.textContent).toBe("2 of 4 keys set in .env. Ask before running code is on. Settings");
  expect(container.querySelector("#idle-count")?.textContent).toBe("40");
});

test("tabs select, stop and suggestions call back", () => {
  const onTab = vi.fn();
  const run = asRun(fixtureCase("tabs/forge").state.run);
  render(<Tabs run={run} onSelect={onTab} />);
  fireEvent.click(screen.getByRole("tab", { name: /Code/ }));
  expect(onTab).toHaveBeenCalledWith("code");
  const onSuggest = vi.fn();
  render(<Idle count={40} weatherKeySet={false} askExec onSuggest={onSuggest} />);
  fireEvent.click(screen.getByText(/Build a Caesar cipher tool/));
  expect(onSuggest).toHaveBeenCalledWith(0);
});

const savedRun = (): Run => asRun(fixtureCase("banner/saved").state.run);

/** Runs scramble() with motion on and counts the animation frames it asks for. */
function withMotion(fn: (frames: () => number) => void) {
  setReducedMotion(false);
  const raf = vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
  try {
    fn(() => raf.mock.calls.length);
  } finally {
    raf.mockRestore();
    setReducedMotion(true);
  }
}

test("a bench remounted with a saved banner doesn't decode the name again (renderBench never scrambles)", () => {
  withMotion((frames) => {
    render(<Bench run={savedRun()} live={false} panel={null} onTab={noop} onStop={noop} onOpenTool={noop} />);
    expect(screen.getByText("caesar_cipher")).toBeInTheDocument();
    expect(frames()).toBe(0);
  });
});

test("a banner set after the bench mounted decodes its name (setBanner, line 1120)", () => {
  withMotion((frames) => {
    const run = savedRun();
    const bare = { ...run, banner: null };
    const noop2 = { panel: null, onTab: noop, onStop: noop, onOpenTool: noop };
    const { rerender } = render(<Bench run={bare} live {...noop2} />);
    expect(frames()).toBe(0);
    rerender(<Bench run={run} live {...noop2} />);
    expect(frames()).toBeGreaterThan(0);
  });
});

test("the retry packet shows only when retrying() is called after the strip mounted", () => {
  const run = { ...asRun(fixtureCase("strip/forge-retry").state.run), retrying: true };
  const link = () => document.querySelector('[data-link="forger-tester"]')!;
  const { rerender, unmount } = render(<Strip run={run} />);
  expect(link()).not.toHaveClass("retrying");
  rerender(<Strip run={{ ...run, retrying: false }} />);
  expect(link()).not.toHaveClass("retrying");
  rerender(<Strip run={{ ...run, retrying: true }} />);
  expect(link()).toHaveClass("retrying");
  unmount();
  const fresh = render(<Strip run={{ ...run, retrying: false }} />);
  fresh.rerender(<Strip run={{ ...run, retrying: true }} />);
  expect(link()).toHaveClass("retrying");
});

test("Stop run and Open in vault call back", () => {
  const onStop = vi.fn();
  const onOpenTool = vi.fn();
  const run = { ...savedRun(), status: "running" as const };
  render(<Bench run={run} live panel={null} onTab={noop} onStop={onStop} onOpenTool={onOpenTool} />);
  fireEvent.click(screen.getByRole("button", { name: "Stop run" }));
  expect(onStop).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("link", { name: "Open in vault" }));
  expect(onOpenTool).toHaveBeenCalledWith("caesar_cipher");
});
