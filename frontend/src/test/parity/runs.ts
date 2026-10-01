import type { Run } from "../../store/types";

/** Fixture run objects are the reference's; they have no id or sessionId. */
export function asRun(json: unknown): Run {
  const r = json as Partial<Run> & { n: number };
  return { id: `run-${r.n}`, sessionId: "s", ...r } as Run;
}
