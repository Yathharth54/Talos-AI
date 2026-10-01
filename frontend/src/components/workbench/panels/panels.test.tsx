import { fireEvent, render, screen } from "@testing-library/react";
import { allFlows, expectParity, fixtureCase, flow } from "../../../test/parity";
import { asRun } from "../../../test/parity/runs";
import { ssr } from "../../../test/ssr";
import type { VaultTool } from "../../../store/types";
import { earlierData, Panel } from "./Panel";
import { clearTestMarks } from "./TestsPanel";

const noop = () => {};

const CASES = [
  "panel/code-typing", "panel/code-changed", "panel/tests-none", "panel/tests-mixed", "panel/tests-smoke-prev",
  "panel/attempts-none", "panel/attempts", "panel/call-resolving", "panel/call-result-record", "panel/call-error-health",
  "panel/call-no-args", "panel/call-pending-approval", "panel/history", "panel/history-gone",
];

test.each(CASES)("%s", (id) => {
  const c = fixtureCase(id);
  const run = asRun(c.state.run);
  const tool = (c.state.tool as VaultTool | null) ?? undefined;
  expectParity(ssr(<Panel run={run} isCurrent={false} tool={tool} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />), c.html!);
});

test("every flow checkpoint's panel matches panelHtml()", () => {
  let n = 0;
  for (const f of allFlows()) {
    for (const s of Object.values(flow(f).snaps)) {
      if (!s.pure) continue;
      const run = asRun(s.run);
      const tools = s.vault as VaultTool[];
      const others = s.sessionRuns.map(asRun);
      const html = ssr(
        <Panel
          run={run}
          isCurrent={s.isCurrent}
          tool={tools.find((t) => t.name === run.toolName)}
          earlier={earlierData(others, run, s.viewSession)}
          onAsk={noop}
          onOpenTool={noop}
          onRun={noop}
        />,
      );
      expectParity(html, s.pure.panel);
      n++;
    }
  }
  expect(n).toBeGreaterThan(30);
});

test("the retry button asks again and Earlier opens a run", () => {
  const onAsk = vi.fn();
  const c = fixtureCase("panel/call-error-health");
  render(<Panel run={asRun(c.state.run)} isCurrent={false} tool={undefined} earlier={null} onAsk={onAsk} onOpenTool={noop} onRun={noop} />);
  fireEvent.click(screen.getByText("Ask again with shift 7"));
  expect(onAsk).toHaveBeenCalledWith('Decrypt this Caesar cipher message with shift 7: "AHSVZ HNLUA"');
});

test("a test drawn once keeps the done tick on the next render", () => {
  const c = fixtureCase("panel/tests-mixed");
  const run = asRun(c.state.run);
  const { rerender, container } = render(<Panel run={run} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  const next = { ...run, tests: { ...run.tests!, list: run.tests!.list.map((t, i) => (i === 2 ? { ...t, state: "passed" as const } : t)) } };
  rerender(<Panel run={next} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  const ticks = [...container.querySelectorAll("svg.tick")].map((s) => s.getAttribute("class"));
  expect(ticks).toEqual(["tick done", "tick"]);
  expect(container.querySelector("li.failed")!.className).toBe("failed");
});

const unmarked = (run: ReturnType<typeof asRun>) => ({
  ...run,
  tests: { ...run.tests!, list: run.tests!.list.map((t) => ({ ...t, drawn: undefined, flashed: undefined })) },
});
const drawnState = (container: HTMLElement) => ({
  ticks: [...container.querySelectorAll("svg.tick")].map((s) => s.getAttribute("class")),
  failed: container.querySelector("li.failed")!.className,
});

test("a re-render that doesn't change the tests isn't a renderPanel(): the tick stays undrawn (weather-save flow)", () => {
  const run = { ...unmarked(asRun(fixtureCase("panel/tests-mixed").state.run)), id: "run-redraw" };
  const { rerender, container } = render(<Panel run={run} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  rerender(<Panel run={{ ...run, caption: "something else" }} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  expect(drawnState(container)).toEqual({ ticks: ["tick"], failed: "failed just-failed" });
  rerender(<Panel run={{ ...run, tests: { ...run.tests! } }} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  expect(drawnState(container)).toEqual({ ticks: ["tick done"], failed: "failed" });
});

test("after clearTestMarks() (demo reset), a replayed run's tests animate again", () => {
  const run = unmarked(asRun(fixtureCase("panel/tests-mixed").state.run));
  const first = render(<Panel run={run} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  first.unmount();
  clearTestMarks();
  const { container } = render(<Panel run={run} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  expect(drawnState(container)).toEqual({ ticks: ["tick"], failed: "failed just-failed" });
});

test("a different run with the same test names animates its own tests", () => {
  const base = unmarked(asRun(fixtureCase("panel/tests-mixed").state.run));
  const first = render(<Panel run={{ ...base, id: "run-a" }} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  first.unmount();
  const { container } = render(<Panel run={{ ...base, id: "run-b" }} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  expect(drawnState(container)).toEqual({ ticks: ["tick"], failed: "failed just-failed" });
});

test("server rendering a panel with layout effects prints no warnings", () => {
  const spy = vi.spyOn(console, "error");
  ssr(<Panel run={asRun(fixtureCase("panel/code-typing").state.run)} isCurrent={false} tool={undefined} earlier={null} onAsk={noop} onOpenTool={noop} onRun={noop} />);
  expect(spy).not.toHaveBeenCalled();
  spy.mockRestore();
});
