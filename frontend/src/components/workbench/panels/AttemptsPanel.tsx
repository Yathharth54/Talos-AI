import { COPY, fill } from "../../../lib/copy";
import type { Attempt } from "../../../store/types";
import { bareZeros } from "../../../lib/style";

/** The attempts panel (attemptsHtml, lines 1201–1205). */
export function AttemptsPanel({ attempts }: { attempts: Attempt[] | undefined }) {
  const a = attempts || [];
  if (!a.length) return <p className="muted">{COPY.attempts.none}</p>;
  return (
    <>
      <ol className="attempts">
        {a.map((x) => (
          <li key={x.n}>
            <span className="a-n">{fill(COPY.attempts.n, { n: x.n })}</span>
            <span className="a-r">
              <span>{x.ok == null ? <span className="gold">{COPY.attempts.underTest}</span> : x.ok ? COPY.attempts.passed : COPY.attempts.failed}</span>
              <span>{x.detail || ""}</span>
            </span>
          </li>
        ))}
      </ol>
      <p className="muted" style={{ margin: "0", fontSize: "13px" }} ref={bareZeros}>
        {COPY.attempts.note}
      </p>
    </>
  );
}
