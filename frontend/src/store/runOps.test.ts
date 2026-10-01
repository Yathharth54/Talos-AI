import { fixtureCase, snap } from "../test/parity";
import { asRun } from "../test/parity/runs";
import { clearFresh, flow, initStrip, log, logPop, newRun, railPercent, setNode, setTab, startCmd, typeCmd, endCmd } from "./runOps";

const base = () => newRun({ id: "run-6", n: 6, query: "q", sessionId: "s" });

test("initStrip builds the reference's nodes for every variant", () => {
  const ref = asRun(fixtureCase("strip/forge-pending").state.run);
  expect(initStrip(base(), "forge").nodes).toEqual(ref.nodes);
  const vault = initStrip(base(), "vault");
  expect(vault.nodes.skip).toEqual({ label: "Forge sub-graph skipped", llm: false, state: "skip" });
  expect(Object.keys(initStrip(base(), "chat").nodes)).toEqual(["planner", "answer"]);
});

test("initStrip with keep carries shared steps across variants", () => {
  const run = setNode(initStrip(base(), "forge"), "planner", "done");
  const v = initStrip(run, "vault", true);
  expect(v.nodes.planner!.state).toBe("done");
  expect(v.nodes.skip!.state).toBe("skip");
});

test("newRun starts like the reference's submit()", () => {
  const ref = asRun(fixtureCase("bench/planning").state.run);
  const run = initStrip(newRun({ id: "x", n: ref.n, query: ref.query, sessionId: "s" }), "forge");
  for (const k of ["tab", "title", "label", "status", "strip", "nodes", "links", "tabs"] as const) expect(run[k]).toEqual(ref[k]);
});

test("setNode keeps the label unless given one; flow lights and counts", () => {
  let run = initStrip(base(), "primitive");
  run = setNode(run, "executor", "active", "Executor, waiting for you");
  expect(run.nodes.executor).toMatchObject({ state: "active", label: "Executor, waiting for you" });
  run = setNode(run, "executor", "done");
  expect(run.nodes.executor!.label).toBe("Executor, waiting for you");
  run = flow(flow(run, "planner", "primitive"), "planner", "primitive");
  expect(run.links["planner-primitive"]).toBe(true);
  expect(run.flows!["planner-primitive"]).toBe(2);
});

test("log clears carets and freshness, logPop removes the last line, the command types in", () => {
  let run = startCmd(base(), "hello world");
  run = typeCmd(run, 5);
  expect(run.log[0]).toMatchObject({ kind: "cmd", shown: 5, typing: true });
  run = endCmd(run);
  expect(run.log[0]).toMatchObject({ shown: null, typing: false });
  run = log(run, "test", "running", "g", { caret: true });
  run = log(run, "test", "4 of 5 passed, retrying", "g");
  expect(run.log[1]).toMatchObject({ caret: false, fresh: false });
  expect(run.log[2]).toMatchObject({ kind: "ln", caret: false, fresh: true, tone: "g" });
  run = log(run, "", "test_decrypt_reverses_encrypt", "", { sub: true });
  expect(run.log[3]!.kind).toBe("sub");
  expect(logPop(run).log).toHaveLength(3);
});

test("railPercent matches updateRail()", () => {
  expect(railPercent(asRun(fixtureCase("bench/planning").state.run))).toBe(0);
  const planning = snap("caesar-forge", "planning");
  expect(railPercent(asRun(planning.run))).toBe(7);
  expect(planning.regions["#bench"]).toContain("width: 7%");
  expect(railPercent(asRun(fixtureCase("bench/chat-done").state.run))).toBe(100);
});

test("a fresh line loses its flag when the log redraws: typing a command or showing the Log tab", () => {
  const withLine = () => log(base(), "plan", "one", "");
  expect(withLine().log[0]).toMatchObject({ fresh: true });
  expect(setTab(withLine(), "code").log[0]).toMatchObject({ fresh: true });
  expect(setTab(withLine(), "log").log[0]).toMatchObject({ fresh: false });
  expect(startCmd(withLine(), "ls").log[0]).toMatchObject({ fresh: false });
  expect(clearFresh(base())).toEqual(base());
});
