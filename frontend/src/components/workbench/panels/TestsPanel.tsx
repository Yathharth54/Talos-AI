import { useEffect } from "react";
import { COPY, fill } from "../../../lib/copy";
import type { Attempt, Smoke, TestsState } from "../../../store/types";
import { TickIcon, XIcon } from "../../icons";
import { bareZeros } from "../../../lib/style";

/* What earlier renders drew: the reference's `x.drawn = true` / `x.flashed = true` (lines 1188–1191), kept out of the store.
   Keyed by run id, attempt and test name. */
const drawnSet = new Set<string>();
const flashedSet = new Set<string>();

/** Forgets every draw mark. The demo reset calls it, because the run counter (and so the run ids) restart there. */
export function clearTestMarks(): void {
  drawnSet.clear();
  flashedSet.clear();
}

type TestsPanelProps = { runId: string; tests: TestsState | undefined; smoke: Smoke | null | undefined; attempts: Attempt[] | undefined };

/** The tests panel (testsHtml, lines 1181–1200). */
export function TestsPanel({ runId, tests, smoke, attempts }: TestsPanelProps) {
  useEffect(() => {
    if (!tests) return;
    for (const x of tests.list) {
      const k = `${runId}:${tests.attempt}:${x.name}`;
      if (x.state === "passed") drawnSet.add(k);
      if (x.state === "failed") flashedSet.add(k);
    }
  });
  if (!tests) return <p className="muted">{COPY.tests.none}</p>;
  const passed = tests.list.filter((x) => x.state === "passed").length;
  const done = tests.list.every((x) => x.state === "passed" || x.state === "failed");
  const right = done ? fill(COPY.tests.passedOf, { p: passed, k: tests.list.length }) : fill(COPY.tests.running, { n: tests.attempt });
  const failedAttempt = attempts && attempts.length > 1 ? attempts.find((a) => !a.ok) : undefined;
  return (
    <div className="grid2">
      <figure className="fig">
        <figcaption className="fig-cap">
          <span>{COPY.tests.unit}</span>
          <span className="r">{right}</span>
        </figcaption>
        <ul className="tests">
          {tests.list.map((x) => {
            const k = `${runId}:${tests.attempt}:${x.name}`;
            const flash = x.state === "failed" && !(x.flashed || flashedSet.has(k)) ? " just-failed" : "";
            return (
              <li key={x.name} className={`${x.state}${flash}`}>
                <span>{x.name}</span>
                <span className="st">
                  {x.state === "passed" ? (
                    <>
                      <TickIcon done={!!x.drawn || drawnSet.has(k)} />
                      {COPY.tests.passed}
                    </>
                  ) : x.state === "failed" ? (
                    <>
                      <XIcon />
                      {COPY.tests.failed}
                    </>
                  ) : (
                    x.state
                  )}
                </span>
                {x.why ? <span className="why">{x.why}</span> : null}
              </li>
            );
          })}
        </ul>
      </figure>
      <div className="stack">
        {smoke ? (
          <figure className="fig">
            <figcaption className="fig-cap">
              <span>{COPY.tests.smoke}</span>
              <span className="r">{COPY.tests.smokeCap}</span>
            </figcaption>
            <div className="smoke-body">
              <div className="muted">{smoke.call}</div>
              <div>
                {smoke.result ? (
                  smoke.result
                ) : (
                  <span className="gold">
                    {COPY.tests.smokeRunning}
                    <span className="caret" aria-hidden="true"></span>
                  </span>
                )}
              </div>
            </div>
          </figure>
        ) : null}
        {failedAttempt ? (
          <div className="stack" style={{ gap: "6px", padding: "0 4px" }} ref={bareZeros}>
            <p style={{ margin: "0", fontSize: "14px" }} ref={bareZeros}>{fill(COPY.tests.prevFailed, { n: failedAttempt.n })}</p>
            <p className="mono muted" style={{ margin: "0", fontSize: "12px", lineHeight: "1.6", overflowWrap: "anywhere" }} ref={bareZeros}>
              {failedAttempt.detail}
            </p>
          </div>
        ) : null}
        <p className="muted" style={{ margin: "0", fontSize: "13px", lineHeight: "1.55", padding: "0 4px" }} ref={bareZeros}>
          {fill(COPY.tests.note, { s: 10 })}
        </p>
      </div>
    </div>
  );
}
