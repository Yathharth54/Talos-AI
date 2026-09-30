import { fireEvent, render, screen } from "@testing-library/react";
import { allFlows, expectParity, fixtureCase, flow } from "../../test/parity";
import { asRun } from "../../test/parity/runs";
import { innerOf, ssr } from "../../test/ssr";
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
