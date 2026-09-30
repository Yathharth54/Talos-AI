import { act, render, screen } from "@testing-library/react";
import { createStores, StoresProvider, updateRun, useRuns } from "./stores";
import { newRun } from "./runOps";

function Label({ id }: { id: string }) {
  const label = useRuns((s) => s.byId[id]?.label);
  return <span>{label}</span>;
}

test("components re-render from store updates, and getState is synchronous", () => {
  const stores = createStores({ tools: [], settings: { askExec: true, env: {}, model: "m" }, sessions: [], runs: [newRun({ id: "r", n: 1, query: "q", sessionId: "s1" })], current: { id: "s1", name: "Session 1", started: "2026-09-30T12:00" }, count: 1 });
  render(<StoresProvider stores={stores}><Label id="r" /></StoresProvider>);
  expect(screen.getByText("Planning")).toBeInTheDocument();
  act(() => updateRun(stores, "r", (r) => ({ ...r, label: "Sub-task 1 of 1, needs a new tool" })));
  expect(stores.runs.get().byId.r!.label).toBe("Sub-task 1 of 1, needs a new tool");
  expect(screen.getByText("Sub-task 1 of 1, needs a new tool")).toBeInTheDocument();
});
