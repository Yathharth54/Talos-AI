import { render } from "@testing-library/react";
import { fixtureCase } from "../../../test/parity";
import { asRun } from "../../../test/parity/runs";
import { TestsPanel } from "./TestsPanel";

/* React may throw a memoised value away and compute it again (useMemo's documented contract). The panel's draw
   marks must not depend on it being kept: here every useMemo call recomputes. */
vi.mock("react", async (orig) => {
  const react = await orig<typeof import("react")>();
  return { ...react, useMemo: <T,>(fn: () => T) => fn() };
});

test("a re-render that isn't a redraw keeps the last redraw's marks, even when React drops memoised values", () => {
  const run = asRun(fixtureCase("panel/tests-mixed").state.run);
  const tests = { ...run.tests!, list: run.tests!.list.map((t) => ({ ...t, drawn: undefined, flashed: undefined })) };
  const props = { runId: "run-memo", tests, smoke: run.smoke, attempts: run.attempts };
  const { rerender, container } = render(<TestsPanel {...props} />);
  const state = () => ({
    ticks: [...container.querySelectorAll("svg.tick")].map((s) => s.getAttribute("class")),
    failed: container.querySelector("li.failed")!.className,
  });
  expect(state()).toEqual({ ticks: ["tick"], failed: "failed just-failed" });
  rerender(<TestsPanel {...props} attempts={run.attempts ? [...run.attempts] : undefined} />);
  expect(state()).toEqual({ ticks: ["tick"], failed: "failed just-failed" });
  rerender(<TestsPanel {...props} tests={{ ...tests }} />);
  expect(state()).toEqual({ ticks: ["tick done"], failed: "failed" });
});
