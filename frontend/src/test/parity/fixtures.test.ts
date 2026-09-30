import { allFlows, fixtureCase, fixtureSha, flow, referenceSha } from ".";

test("fixtures were generated from the current reference", () => {
  expect(fixtureSha).toBe(referenceSha());
});

test("every flow has its snapshots", () => {
  expect(allFlows()).toHaveLength(18);
  expect(Object.keys(flow("caesar-forge").snaps).sort()).toEqual(
    ["args", "end", "forging", "planning", "reader", "retry", "saved", "sessions", "settings", "smoke", "test-failed", "vault"].sort(),
  );
  expect(flow("stop-during-tests").snaps.end!.regions["#bench"]).toContain("Tester, stopped");
});

test("cases carry html or a value", () => {
  expect(fixtureCase("strip/forge-pending").html).toContain('data-node="planner"');
  expect(fixtureCase("lib/highlight-caesar").value).toHaveLength(63);
});
